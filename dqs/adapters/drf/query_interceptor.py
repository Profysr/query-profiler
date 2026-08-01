import inspect
import time
from typing import Any, Callable, Dict, List, Optional
from django.db import connection

"""
QueryInterceptor is a custom Context Manager. Its sole job is to attach directly to Django's database driver connection (django.db.connection) while a block of code runs. Every time SQL hits the database, it does three things:

- Intercepts the query.
- Measures how long it took in milliseconds using high-precision timers.
- Inspects the Python call stack right at that exact instant to pinpoint the precise file and line number in user code (e.g., views.py:42) that triggered the query.
"""

class QueryInterceptor:
    """
    A context manager that intercepts Django database queries at the driver boundary,
    capturing SQL, execution time, and dynamically tracing the origin back to application code.
    """
    def __init__(self):
        self.captured_queries: List[Dict[str, Any]] = []

    def __enter__(self):
        self._hook = connection.execute_wrapper(self._wrapper)
        self._hook.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._hook.__exit__(exc_type, exc_value, traceback)

    def _wrapper(self, execute: Callable, sql: str, params: Any, many: bool, context: Dict[str, Any]) -> Any:
        start_time = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            duration = (time.perf_counter() - start_time) * 1000.0
            source_loc = self._extract_source_location()
            self.captured_queries.append({
                "sql": sql,
                "time_ms": duration if duration >= 1.0 else duration,
                "src_loc": source_loc,
            })

    def _extract_source_location(self) -> Optional[str]:
        """Inspects active call frames to pinpoint the user file and line number triggering the query."""
        for frame_info in inspect.stack():
            filename = frame_info.filename
            # Filter out framework internals (Django, DRF, DQS runner package itself)
            if any(pkg in filename for pkg in ["site-packages", "django/", "rest_framework/", "dqs/core/", "dqs/adapters/"]):
                continue
            
            parts = filename.split("/")
            short_path = "/".join(parts[-2:]) if len(parts) >= 2 else filename
            return f"{short_path}:{frame_info.lineno}"
        return None