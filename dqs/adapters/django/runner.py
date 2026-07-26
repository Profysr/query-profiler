# dqs/adapters/django/runner.py
import time
import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

@dataclass
class ExecutionResult:
    route: str
    status_code: int
    metrics: Dict[str, Any] = field(default_factory=dict)
    queries: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    side_effect_warnings: List[str] = field(default_factory=list)


class DjangoSandboxRunner:
    def __init__(self):
        # Security Guardrail: Refuse to execute if DEBUG is disabled
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DjangoSandboxRunner requires DEBUG=True for safety.")
        self.factory = RequestFactory()

    def execute_isolated(self, path: str, method: str = "GET", data: Optional[dict] = None) -> ExecutionResult:
        """
        Executes a route inside an atomic database transaction savepoint that is 
        instantly rolled back. Captures all SQL queries, execution time, and status codes.
        """
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return ExecutionResult(route=path, status_code=400, error=f"Invalid HTTP method: {method}")

        # Step 1: Resolve the view handler from the URL resolver
        from django.urls import resolve
        try:
            resolved_match = resolve(path)
        except Exception as e:
            return ExecutionResult(route=path, status_code=404, error=f"Route resolution failed: {str(e)}")

        # Step 2: Build the WSGI request object
        request_func = getattr(self.factory, method.lower(), None)
        if not request_func:
            return ExecutionResult(route=path, status_code=405, error=f"Unsupported method request generator: {method}")

        request = request_func(path, data or {})
        
        # Security: Bypass authentication middleware constraints for sandbox testing
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()

        # Step 3: Run inside an isolated rolling-back database transaction
        queries_captured = []
        status_code = 500
        start_time = time.perf_counter()
        db_start_time = 0.0
        db_duration = 0.0

        sid = transaction.savepoint()
        try:
            with CaptureQueriesContext(connection) as cqc:
                db_start = time.perf_counter()
                
                # Execute the view callback directly
                response = resolved_match.func(request, *resolved_match.args, **resolved_match.kwargs)
                
                db_duration = (time.perf_counter() - db_start) * 1000.0
                queries_captured = cqc.captured_queries
                status_code = getattr(response, "status_code", 200)

        except Exception as e:
            status_code = 500
            return ExecutionResult(
                route=path,
                status_code=status_code,
                error=f"Exception raised inside view execution: {str(e)}"
            )
        finally:
            # Absolute Guarantee: Roll back all database modifications immediately
            transaction.savepoint_rollback(sid)

        total_duration = (time.perf_counter() - start_time) * 1000.0

        # Step 4: Format the enriched execution metrics payload required by v0.4.0 (MCP Agent)
        metrics = {
            "total_time_ms": round(total_duration, 2),
            "db_time_ms": round(db_duration, 2),
            "total_queries": len(queries_captured),
            "unique_fingerprints": len(set(q["sql"] for q in queries_captured)),
        }

        formatted_queries = [
            {"sql": q["sql"], "time_ms": float(q["time"])} 
            for q in queries_captured
        ]

        return ExecutionResult(
            route=path,
            status_code=status_code,
            metrics=metrics,
            queries=formatted_queries,
        )