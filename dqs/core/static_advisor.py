import ast
from typing import Any

"""
It allows DQS to inspect code paths—even ones without URLs, like signal handlers or background jobs—and flag dangerous patterns (like DB queries inside loops or synchronous network requests) before anything is executed.
"""

# 1. Externalized Rule Sets (O(1) Set Lookups)
DJANGO_ORM_METHODS: set[str] = {
    "get", "filter", "exclude", "all", "first", "last",
    "create", "update", "delete", "count", "exists",
    "select_related", "prefetch_related", "values", "values_list"
}

BLOCKING_CALL_PREFIXES: set[str] = {
    "requests.get", "requests.post", "requests.put", "requests.delete", "requests.patch",
    "urllib.request", "smtplib.SMTP", "time.sleep"
}

class StaticASTAdvisor(ast.NodeVisitor):
    """
    Framework-agnostic static AST scanner to identify ORM anti-patterns inside loops,
    blocking calls, and risky code constructs without requiring database execution.
    """
    def __init__(self, source_code: str, filename: str = "<string>"):
        self.source_code = source_code
        self.filename = filename
        self.findings: list[dict[str, Any]] = []
        self._loop_depth = 0
        self.import_map: dict[str, str] = {}
        self.queried_fields: list[str] = []

    def run(self) -> list[dict[str, Any]]:
        try:
            tree = ast.parse(self.source_code, filename=self.filename)
            self.visit(tree)
        except Exception as e:
            self.findings.append({
                "type": "AST_PARSE_ERROR",
                "message": f"Could not parse source code: {e!s}",
                "line": 0,
            })
        return self.findings

    def visit_Import(self, node: ast.Import) -> None:
        """Tracks `import X` / `import X as Y` so later calls can be resolved back to X."""
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".")[0]
            self.import_map[local_name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Tracks `from X import Y` / `from X import Y as Z` so `Y(...)` resolves to `X.Y`."""
        module = node.module or ""
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.import_map[local_name] = f"{module}.{alias.name}" if module else alias.name
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        call_repr = self._get_call_name(node)

        # 1. ORM Call Inside Loop Detection
        if self._loop_depth > 0:
            is_orm, confidence = self._is_orm_call(node, call_repr)
            if is_orm:
                severity = "high" if confidence == "high" else "low"
                message = (
                    f"Potential N+1 query pattern: ORM call '{call_repr}' detected inside a loop at line {node.lineno}."
                    if confidence == "high"
                    else f"Possible N+1 query pattern: '{call_repr}' inside a loop at line {node.lineno} — "
                        f"method name matches common ORM calls, but receiver isn't confirmed as a queryset/manager."
                )
                self.findings.append({
                    "type": "ORM_CALL_IN_LOOP",
                    "message": message,
                    "line": node.lineno,
                    "severity": severity,
                })

        # 2. Blocking Network / Sync Call Detection
        if self._is_blocking_call(call_repr):
            self.findings.append({
                "type": "BLOCKING_EXTERNAL_CALL",
                "message": f"Blocking network/IO call '{call_repr}' detected inside code path at line {node.lineno}.",
                "line": node.lineno,
                "severity": "medium",
            })

        # 3. Collect field names from filter/exclude/order_by calls, regardless of loop depth — used by schema_advisor.py for missing-index checks.
        method_name = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if method_name in ("filter", "exclude", "order_by"):
            for kw in node.keywords:
                if kw.arg:
                    self.queried_fields.append(kw.arg)
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self.queried_fields.append(arg.value)

        self.generic_visit(node)

    # Name fragments that strongly suggest the receiver is a queryset/manager, used to upgrade confidence on generically-named methods like .get()/.filter() that would otherwise false-positive on any unrelated class with those methods.
    _QUERYSET_HINT_FRAGMENTS = ("queryset", "_set", "qs", "manager")

    def _is_orm_call(self, node: ast.Call, call_repr: str) -> tuple:
        """
        Determines if a call node is a Django ORM query using AST structure.
        Returns (is_match, confidence) — confidence is "high" or "low".
        "low" confidence findings are still reported, but at reduced severity, since generic method names (.get(), .filter(), .all()) are common on non-Django classes too and shouldn't be flagged as loudly.
        """
        # High confidence: explicit manager access — unambiguous Django pattern.
        if ".objects." in call_repr or call_repr.startswith("objects."):
            return True, "high"

        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            if method_name in DJANGO_ORM_METHODS:
                # Upgrade confidence if the receiver's name hints at a queryset/manager (e.g. `author.book_set.all()`, `self.queryset.filter()`, `qs.filter()`).
                receiver = self._unparse_node(node.func.value).lower()
                if any(hint in receiver for hint in self._QUERYSET_HINT_FRAGMENTS):
                    return True, "high"
                # Otherwise it's a generic name match — real but low-confidence.
                return True, "low"

        return False, None

    def _is_blocking_call(self, call_repr: str) -> bool:
        """Checks if the call representation starts with a known blocking I/O prefix."""
        return any(call_repr.startswith(prefix) for prefix in BLOCKING_CALL_PREFIXES)

    def _get_call_name(self, node: ast.Call) -> str:
        """Extracts full method dot-notation string from AST Call node, resolving import aliases."""
        if isinstance(node.func, ast.Attribute):
            value = self._unparse_node(node.func.value)
            resolved_value = self._resolve_alias(value)
            return f"{resolved_value}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            return self._resolve_alias(node.func.id)
        return ""

    def _unparse_node(self, node: ast.AST) -> str:
        """Converts an AST node back into a plain string representation."""
        if hasattr(ast, "unparse"):
            return ast.unparse(node)
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._unparse_node(node.value)}.{node.attr}"
        return ""

    """
    ast.NodeVisitor visits nodes in the order they appear, so import_map is being built as it goes. If an import statement appears after the call that uses it in source order (extremely unusual but technically legal at module scope with conditional imports, or if someone analyzes a code fragment out of context), the call would be checked before the alias is known. For typical top-of-file imports this is a non-issue — just don't be surprised if a deliberately adversarial test case exposes it later.
    """
    def _resolve_alias(self, name: str) -> str:
        """Resolves a local name/alias back to its real fully-qualified import path, if known."""
        base = name.split(".")[0]
        if base in self.import_map:
            resolved_base = self.import_map[base]
            remainder = name[len(base):]  # preserves any trailing ".suffix" already present
            return f"{resolved_base}{remainder}"
        return name