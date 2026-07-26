import inspect
from typing import Any
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext


class DjangoSandboxRunner:
    """Executes endpoint requests in a zero-migration, rolling-back transaction sandbox."""

    ALLOWED_METHODS: set[str] = {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
    }

    # Things a database rollback CANNOT undo — flagged, not blocked.
    SIDE_EFFECT_PATTERNS: list[str] = [
        "requests.",
        "httpx.",
        "smtplib",
        "send_mail",
        ".delay(",
        ".apply_async(",
        "group_send(",
    ]

    def execute_isolated(
        self,
        view_func: Any,
        method: str = "GET",
        path: str = "/",
        user: Any = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Runs the target view function inside a rolling-back transaction and captures queries."""

        # 1. Hard production guardrail.
        if not getattr(settings, "DEBUG", False):
            raise PermissionDenied(
                "DQS Sandbox execution is strictly disabled when DEBUG=False."
            )

        # 2. Strict method whitelist.
        http_method = method.lower()
        if http_method not in self.ALLOWED_METHODS:
            raise ValueError(
                f"Invalid HTTP method '{method}'. Allowed methods: {sorted(self.ALLOWED_METHODS)}"
            )

        warnings = self._detect_side_effects(view_func)

        # 3. Wrap execution in a transaction savepoint.
        with transaction.atomic():
            sid = transaction.savepoint()
            try:
                factory = RequestFactory()
                request_builder = getattr(factory, http_method)

                request = request_builder(
                    path, data=data or {}, content_type="application/json"
                )

                if user is not None:
                    request.user = user

                ctx = None
                status_code = 500
                try:
                    with CaptureQueriesContext(connection) as ctx:
                        response = view_func(request)
                        status_code = getattr(response, "status_code", 200)
                except Exception as exc:
                    warnings.append(
                        f"View execution raised an exception: {type(exc).__name__}: {exc}"
                    )

                captured_queries = (
                    [
                        {"sql": q["sql"], "time": float(q["time"])}
                        for q in ctx.captured_queries
                    ]
                    if ctx is not None
                    else []
                )

                return {
                    "status_code": status_code,
                    "queries": captured_queries,
                    "query_count": len(captured_queries),
                    "warnings": warnings,
                }
            finally:
                # Guaranteed rollback
                transaction.savepoint_rollback(sid)

    def _detect_side_effects(self, view_func: Any) -> list[str]:
        """Greps view source code for unhandled external side effects."""
        warnings: list[str] = []
        try:
            # Check view_class (Django standard), cls (DRF standard), or fallback to view_func
            target = getattr(
                view_func, "view_class", getattr(view_func, "cls", view_func)
            )
            source = inspect.getsource(target)

            for pattern in self.SIDE_EFFECT_PATTERNS:
                if pattern in source:
                    warnings.append(
                        f"Potential side-effect detected ('{pattern}'). "
                        "DB writes will roll back, but external side effects will not."
                    )
        except (TypeError, OSError):
            pass

        return warnings