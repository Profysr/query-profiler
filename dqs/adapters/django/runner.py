"""
=============================================================================
ELI5 PSEUDO-FORMAT FLOW MAP (How DjangoSandboxRunner works step-by-step):
=============================================================================
execute_isolated()
 └── 1. Resolve URL & Method [Finds matching route and sets up request factory]
 └── 2. Scan Side Effects [Checks source code for external risks like emails/tasks]
 └── 3. Open Atomic Transaction & Savepoint [Ensures changes can be wiped clean]
      └── 4. Seed Mock Data (Optional) [Populates fake records using model_bakery]
      └── 5. Construct & Run Request [Executes view, capturing queries & stack traces]
      └── 6. Rollback Transaction [Instantly reverts all database modifications]
 └── 7. Analyze Queries [Detects N+1 bottlenecks using SQL fingerprints and locations]
=============================================================================
"""

"""
=============================================================================
ELI5 PSEUDO-FORMAT FLOW MAP (How DjangoSandboxRunner works step-by-step):
=============================================================================
{
  "route": "/api/books/",
  "status_code": 200,
  "metrics": {
    "total_time_ms": 14.25,
    "db_time_ms": 4.12,
    "total_queries": 4,
    "unique_fingerprints": 2,
    "n_plus_one_detected": true
  },
  "queries": [
    {
      "sql": "SELECT \"library_book\".\"id\", \"library_book\".\"title\" FROM \"library_book\"",
      "fingerprint": "SELECT T0.id, T0.title FROM library_book AS T0",
      "time_ms": 1.2,
      "source_location": "api/views.py:28"
    },
    {
      "sql": "SELECT \"library_author\".\"id\", \"library_author\".\"name\" FROM \"library_author\" WHERE \"library_author\".\"id\" = 1",
      "fingerprint": "SELECT T0.id, T0.name FROM library_author AS T0 WHERE T0.id = ?",
      "time_ms": 0.9,
      "source_location": "api/serializers.py:15"
    }
  ],
  "analysis": [
    {
      "fingerprint": "SELECT T0.id, T0.name FROM library_author AS T0 WHERE T0.id = ?",
      "count": 3,
      "source_location": "api/serializers.py:15",
      "suggestion": "Potential N+1 detected on table 'library_author' at `api/serializers.py:15`. Fix by appending `.select_related('author')` to your base queryset.",
      "sample_queries": [
        "SELECT \"library_author\".\"id\", \"library_author\".\"name\" FROM \"library_author\" WHERE \"library_author\".\"id\" = 1",
        "SELECT \"library_author\".\"id\", \"library_author\".\"name\" FROM \"library_author\" WHERE \"library_author\".\"id\" = 2"
      ]
    }
  ],
  "error": null,
  "side_effect_warnings": [],
  "response_body": [
    {"id": 1, "title": "Django Deep Dive", "author": {"id": 1, "name": "Alice"}}
  ],
  "seeded_records": [
    {"pk": 1, "__str__": "Book object (1)"}
  ]
}
"""
import inspect
import json
import traceback
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.urls import resolve, reverse
from django.test.utils import CaptureQueriesContext
from model_bakery import baker
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from dqs.core.analyzer import fingerprint, detect_n_plus_one, suggest_fix


@dataclass
class ExecutionResult:
    route: str
    status_code: int
    metrics: Dict[str, Any] = field(default_factory=dict)
    queries: List[Dict[str, Any]] = field(default_factory=list)
    analysis: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    side_effect_warnings: List[str] = field(default_factory=list)
    response_body: Optional[Any] = None
    seeded_records: List[Dict[str, Any]] = field(default_factory=list)


class DjangoSandboxRunner:
    """
    Executes isolated sandbox profiles for DRF endpoints with full savepoint rollback,
    mock data seeding, primary key tracking, and stack-trace-aware query inspection.
    """
    def __init__(self):
        # Safety check: Ensure the runner only executes in local development mode
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DjangoSandboxRunner requires DEBUG=True for safety.")
        self.factory = APIRequestFactory()

    def execute_isolated(
        self,
        url_name_or_path: str,
        method: str = "GET",
        path_params: Optional[Dict[str, Any]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        user: Optional[Any] = None,
        relationships: Optional[Dict[str, str]] = None,
        seed_count: int = 0,
        target_model: Optional[str] = None,
        content_type: str = "application/json",
    ) -> ExecutionResult:
        method = method.upper()
        path_params = path_params or {}
        query_params = query_params or {}

        # Validate that the HTTP verb is supported
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return ExecutionResult(route=url_name_or_path, status_code=400, error=f"Invalid HTTP method: {method}")

        # Step 1a: Try to build the full URL path using Django's reverse URL lookup
        try:
            resolved_path = reverse(url_name_or_path, kwargs=path_params)
        except Exception:
            resolved_path = url_name_or_path

        # Step 1b: Resolve the URL string into internal Django match metadata (view function, arguments)
        try:
            resolved_match = resolve(resolved_path)
        except Exception as e:
            return ExecutionResult(route=resolved_path, status_code=404, error=f"Route resolution failed: {str(e)}")

        request_func = getattr(self.factory, method.lower(), None)
        if not request_func:
            return ExecutionResult(route=resolved_path, status_code=405, error=f"Unsupported method: {method}")

        # Step 2: Scan the view function's source code for risky outbound side effects (like sending emails)
        side_effect_warnings = self._detect_side_effects(resolved_match.func)

        queries_captured = []
        status_code = 500
        response_body = None
        seeded_records_info = []
        start_time = time.perf_counter()
        db_duration = 0.0

        try:
            # Step 3: Open an atomic database transaction and create a safety savepoint checkpoint
            with transaction.atomic():
                sid = transaction.savepoint()
                try:
                    # Step 4: If mock data was requested, populate fake database records using model_bakery
                    if seed_count > 0 and target_model:
                        model_class = apps.get_model(target_model)
                        created_instances = baker.make(model_class, _quantity=seed_count)
                        
                        # Handle baker output inconsistency: if 1 item is created, it returns an object instead of a list.
                        # This safely normalizes it into a list so we can loop over it uniformly.
                        if not isinstance(created_instances, list):
                            created_instances = [created_instances]
                            
                        # Extract primary keys and string titles of the newly created fake records for debugging logs
                        seeded_records_info = [{"pk": obj.pk, "__str__": str(obj)} for obj in created_instances]

                    # Step 5a: Build the simulated HTTP request payload depending on the method verb
                    if method in {"POST", "PUT", "PATCH"} and data is not None:
                        request = request_func(resolved_path, data=json.dumps(data), content_type=content_type)
                    else:
                        request = request_func(resolved_path, data=query_params if method == "GET" else (data or {}))

                    request.user = user if user is not None else AnonymousUser()
                    request.resolver_match = resolved_match

                    # Step 5b: Run the view function inside Django's query capture context to intercept all database queries
                    with CaptureQueriesContext(connection) as cqc:
                        db_start = time.perf_counter()
                        response = resolved_match.func(request, *resolved_match.args, **resolved_match.kwargs)
                        
                        # Render DRF responses if they are lazy-evaluated
                        if isinstance(response, Response) && hasattr(response, "render"):
                            response.render()
                            
                        db_duration = (time.perf_counter() - db_start) * 1000.0
                        queries_captured = cqc.captured_queries
                        status_code = getattr(response, "status_code", 200)
                        response_body = self._parse_response_body(response)
                finally:
                    # Step 6: Instantly roll back the transaction so NO fake data or changes persist in the database
                    transaction.savepoint_rollback(sid)
        except Exception as e:
            return ExecutionResult(
                route=resolved_path,
                status_code=500,
                error=f"Exception raised inside sandbox execution: {str(e)}",
                side_effect_warnings=side_effect_warnings,
            )

        total_duration = (time.perf_counter() - start_time) * 1000.0

        # Step 7a: Format captured SQL queries and locate their exact source code line via stack traces
        formatted_queries = []
        raw_sql_list = []
        for q in queries_captured:
            sql_text = q["sql"]
            raw_sql_list.append(sql_text)
            
            # Trace back through execution stack frames to find user code file and line number
            source_loc = self._extract_source_location()

            formatted_queries.append({
                "sql": sql_text,
                "fingerprint": fingerprint(sql_text),
                "time_ms": float(q["time"]) * 1000.0 if float(q["time"]) < 1 else float(q["time"]),
                "source_location": source_loc,
            })

        # Step 7b: Run N+1 bottleneck analysis across the collected queries and source lines
        n_plus_one_groups = detect_n_plus_one(raw_sql_list, threshold=3, relationships=relationships)
        analysis_payload = []
        for group in n_plus_one_groups:
            fp = group["fingerprint"]
            analysis_payload.append({
                "fingerprint": fp,
                "count": group["count"],
                "source_location": group.get("source_location"),
                "suggestion": group.get("suggestion"),
                "sample_queries": group.get("sample_queries", []),
            })

        # Bundle overall performance metrics
        metrics = {
            "total_time_ms": round(total_duration, 2),
            "db_time_ms": round(db_duration, 2),
            "total_queries": len(queries_captured),
            "unique_fingerprints": len(set(q["fingerprint"] for q in formatted_queries)),
            "n_plus_one_detected": len(n_plus_one_groups) > 0,
        }

        return ExecutionResult(
            route=resolved_path,
            status_code=status_code,
            metrics=metrics,
            queries=formatted_queries,
            analysis=analysis_payload,
            response_body=response_body,
            seeded_records=seeded_records_info,
            side_effect_warnings=side_effect_warnings,
        )

    def _extract_source_location(self) -> Optional[str]:
        """Helper: Inspects active call frames to pinpoint the user file and line number triggering the query."""
        for frame_info in inspect.stack():
            filename = frame_info.filename
            # Filter out framework internals (Django, DRF, DQS runner package itself)
            if any(pkg in filename for pkg in ["site-packages", "django/", "rest_framework/", "dqs/core/"]):
                continue
            # Format cleanly as relative path and line number (e.g., 'views.py:42')
            parts = filename.split("/")
            short_path = "/".join(parts[-2:]) if len(parts) >= 2 else filename
            return f"{short_path}:{frame_info.lineno}"
        return None

    def _parse_response_body(self, response: Any) -> Optional[Any]:
        """Helper: Safely decodes HTTP response content into a Python dictionary or JSON payload."""
        if hasattr(response, "data"):
            return response.data
        content = getattr(response, "content", None)
        if not content:
            return None
        try:
            return json.loads(content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _detect_side_effects(self, view_func: Any) -> List[str]:
        """Helper: Scans view function source code for dangerous external calls like emails or Celery tasks."""
        warnings = []
        try:
            source_code = inspect.getsource(view_func)
            risky_keywords = {
                "smtplib": "Outbound email sending detected (smtplib).",
                ".delay(": "Asynchronous background task triggered (.delay()).",
                ".apply_async(": "Asynchronous background task triggered (.apply_async()).",
                "requests.post": "Outbound HTTP mutation detected (requests.post).",
                "requests.put": "Outbound HTTP mutation detected (requests.put).",
                "requests.delete": "Outbound HTTP mutation detected (requests.delete).",
                "urllib.request": "Outbound HTTP request detected (urllib).",
            }
            for keyword, message in risky_keywords.items():
                if keyword in source_code:
                    warnings.append(message)
        except (TypeError, OSError):
            pass
        return list(set(warnings))