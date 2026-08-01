import ast
from typing import Any, Dict, Set, List, Optional

"""
It allows DQS to inspect code paths—even ones without URLs, like signal handlers or background jobs—and flag dangerous patterns (like DB queries inside loops or synchronous network requests) before anything is executed.
"""

# 1. Externalized Rule Sets (O(1) Set Lookups)
DJANGO_ORM_METHODS: Set[str] = {
    "get", "filter", "exclude", "all", "first", "last",
    "create", "update", "delete", "count", "exists",
    "select_related", "prefetch_related", "values", "values_list"
}

BLOCKING_CALL_PREFIXES: Set[str] = {
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
        self.findings: List[Dict[str, Any]] = []
        self._loop_depth = 0

    def run(self) -> List[Dict[str, Any]]:
        try:
            tree = ast.parse(self.source_code, filename=self.filename)
            self.visit(tree)
        except Exception as e:
            self.findings.append({
                "type": "AST_PARSE_ERROR",
                "message": f"Could not parse source code: {str(e)}",
                "line": 0,
            })
        return self.findings

    def visit_For(self, node: ast.For) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        call_repr = self._get_call_name(node)

        # 1. ORM Call Inside Loop Detection
        if self._loop_depth > 0 and self._is_orm_call(node, call_repr):
            self.findings.append({
                "type": "ORM_CALL_IN_LOOP",
                "message": f"Potential N+1 query pattern: ORM call '{call_repr}' detected inside a loop at line {node.lineno}.",
                "line": node.lineno,
                "severity": "high",
            })

        # 2. Blocking Network / Sync Call Detection
        if self._is_blocking_call(call_repr):
            self.findings.append({
                "type": "BLOCKING_EXTERNAL_CALL",
                "message": f"Blocking network/IO call '{call_repr}' detected inside code path at line {node.lineno}.",
                "line": node.lineno,
                "severity": "medium",
            })

        self.generic_visit(node)

    def _is_orm_call(self, node: ast.Call, call_repr: str) -> bool:
        """Determines if a call node is a Django ORM query using AST structure."""
        # Check 1: Explicit Manager Access (e.g., User.objects.filter or self.queryset.filter)
        if ".objects." in call_repr or call_repr.startswith("objects."):
            return True

        # Check 2: Attribute method matching against ORM keywords (e.g., qs.filter())
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            if method_name in DJANGO_ORM_METHODS:
                # Ensures it's chained on an attribute call (e.g. obj.filter), not a plain function filter()
                return True

        return False

    def _is_blocking_call(self, call_repr: str) -> bool:
        """Checks if the call representation starts with a known blocking I/O prefix."""
        return any(call_repr.startswith(prefix) for prefix in BLOCKING_CALL_PREFIXES)

    def _get_call_name(self, node: ast.Call) -> str:
        """Extracts full method dot-notation string from AST Call node."""
        if isinstance(node.func, ast.Attribute):
            value = self._unparse_node(node.func.value)
            return f"{value}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            return node.func.id
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