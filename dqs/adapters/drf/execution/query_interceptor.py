import inspect
import json
import os
import time
from collections.abc import Callable
from typing import Any

from django.db import connection

from dqs.adapters.drf.types import ExecutionResult
from dqs.core.analyzer import detect_n_plus_one, fingerprint

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
        self.captured_queries: list[dict[str, Any]] = []

    def __enter__(self):
        self._hook = connection.execute_wrapper(self._wrapper)
        self._hook.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._hook.__exit__(exc_type, exc_value, traceback)

    def _wrapper(self, execute: Callable, sql: str, params: Any, many: bool, context: dict[str, Any]) -> Any:
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

    def _extract_source_location(self) -> str | None:
        """Inspects active call frames to pinpoint the user file and line number triggering the query."""
        # Normalize exclusion paths for cross-platform compatibility
        exclude_patterns = [
            "site-packages",
            "django" + os.sep,
            "rest_framework" + os.sep,
            "dqs" + os.sep + "core" + os.sep,
            "dqs" + os.sep + "adapters" + os.sep,
        ]
        # Also check with forward slash for good measure
        exclude_patterns.extend([
            "django/",
            "rest_framework/",
            "dqs/core/",
            "dqs/adapters/",
        ])

        for frame_info in inspect.stack():
            filename = frame_info.filename
            # Filter out framework internals (Django, DRF, DQS runner package itself)
            if any(pkg in filename for pkg in exclude_patterns):
                continue
            
            parts = filename.split(os.sep)
            short_path = "/".join(parts[-2:]) if len(parts) >= 2 else filename
            return f"{short_path}:{frame_info.lineno}"
        return None


# dqs/analysis/query_analyzer.py
class QueryAnalysisEngine:
    """Processes captured SQL queries, detects N+1 issues, and formats ExecutionResults."""

    @staticmethod
    def parse_response_body(response: Any) -> Any | None:
        """Extracts JSON/Dict payload safely from a Django or DRF Response object."""
        if hasattr(response, "data"):
            return response.data
        
        content = getattr(response, "content", None)
        if not content:
            return None

        try:
            return json.loads(content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    @classmethod
    def build_result(
        cls,
        route: str,
        status_code: int,
        queries_captured: list[dict[str, Any]],
        db_duration: float,
        total_duration: float,
        response_body: Any,
        seeded_records_info: list[dict[str, Any]],
        side_effect_warnings: list[str],
        relationships: dict[str, str] | dict[str, dict[str, str]] | None = None
    ) -> ExecutionResult:
        """Formats raw intercepted queries and calculates N+1 performance metrics."""
        formatted_queries = [
            {
                "sql": q["sql"],
                "fingerprint": fingerprint(q["sql"]),
                "time_ms": q["time_ms"],
                "src_loc": q.get("src_loc"),
            }
            for q in queries_captured
        ]

        n_plus_one_groups = detect_n_plus_one(formatted_queries, threshold=3, relationships=relationships)
        
        analysis_payload = [
            {
                "fingerprint": group["fingerprint"],
                "count": group["count"],
                "src_loc": group.get("src_loc"),
                "suggestion": group.get("suggestion"),
                "sample_queries": group.get("sample_queries", []),
            }
            for group in n_plus_one_groups
        ]

        metrics = {
            "total_time_ms": round(total_duration, 2),
            "db_time_ms": round(db_duration, 2),
            "total_queries": len(queries_captured),
            "unique_fingerprints": len(set(q["fingerprint"] for q in formatted_queries)),
            "n_plus_one_detected": len(n_plus_one_groups) > 0,
        }

        return ExecutionResult(
            route=route,
            status_code=status_code,
            metrics=metrics,
            queries=formatted_queries,
            analysis=analysis_payload,
            response_body=response_body,
            seeded_records=seeded_records_info,
            side_effect_warnings=side_effect_warnings,
        )