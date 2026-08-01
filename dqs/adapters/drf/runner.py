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
      "src_loc": "api/views.py:28"
    },
    {
      "sql": "SELECT \"library_author\".\"id\", \"library_author\".\"name\" FROM \"library_author\" WHERE \"library_author\".\"id\" = 1",
      "fingerprint": "SELECT T0.id, T0.name FROM library_author AS T0 WHERE T0.id = ?",
      "time_ms": 0.9,
      "src_loc": "api/serializers.py:15"
    }
  ],
  "analysis": [
    {
      "fingerprint": "SELECT T0.id, T0.name FROM library_author AS T0 WHERE T0.id = ?",
      "count": 3,
      "src_loc": "api/serializers.py:15",
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
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.urls import resolve, reverse
from model_bakery import baker
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from dqs.core.analyzer import fingerprint, detect_n_plus_one, suggest_fix
from dqs.adapters.drf.query_interceptor import QueryInterceptor
# Import the AST Advisor to replace the old string-matching logic
from dqs.core.static_advisor import StaticASTAdvisor 

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
    Executes isolated sandbox profiles via a universal query interceptor with full savepoint rollback.
    """
    def __init__(self):
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DjangoSandboxRunner requires DEBUG=True for safety.")
        self.factory = APIRequestFactory()

    def profile_callable(
        self,
        func: Callable,
        *args,
        setup: Optional[Callable[[], Any]] = None,
        **kwargs,
    ) -> Tuple[Any, List[Dict[str, Any]], float, Any]:
        """
        Executes any generic Python callable inside an intercepted savepoint block.

        `setup`, if provided, runs INSIDE the same transaction/savepoint (so it's
        still rolled back) but BEFORE the QueryInterceptor attaches — this is where
        mock-data seeding belongs. Queries issued during `setup` are never captured,
        so they can't pollute N+1 detection or query counts for the profiled callable.

        Returns (result, captured_queries, db_duration_ms, setup_result).
        """
        queries_captured = []
        db_duration = 0.0
        result = None
        setup_result = None

        with transaction.atomic():
            sid = transaction.savepoint()
            try:
                # Seeding / setup happens here, inside the rollback boundary, outside the query interceptor.
                if setup is not None:
                    setup_result = setup()

                with QueryInterceptor() as interceptor:
                    db_start = time.perf_counter()
                    result = func(*args, **kwargs)
                    db_duration = (time.perf_counter() - db_start) * 1000.0
                    queries_captured = interceptor.captured_queries
            finally:
                transaction.savepoint_rollback(sid)

        return result, queries_captured, db_duration, setup_result

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

        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return ExecutionResult(route=url_name_or_path, status_code=400, error=f"Invalid HTTP method: {method}")

        try:
            resolved_path = reverse(url_name_or_path, kwargs=path_params)
        except Exception:
            resolved_path = url_name_or_path

        try:
            resolved_match = resolve(resolved_path)
        except Exception as e:
            return ExecutionResult(route=resolved_path, status_code=404, error=f"Route resolution failed: {str(e)}")

        request_func = getattr(self.factory, method.lower(), None)
        if not request_func:
            return ExecutionResult(route=resolved_path, status_code=405, error=f"Unsupported method: {method}")

        # Replaced the old logic with our centralized static analyzer
        side_effect_warnings = self._detect_side_effects(resolved_match.func)

        start_time = time.perf_counter()
        try:
            # Seeding now happens BEFORE the interceptor attaches (see profile_callable's `setup` param) — its INSERT queries are never captured, so they can't inflate query counts or trigger false N+1 flags.
            def _seed():
                seeded_info = []
                if seed_count > 0 and target_model:
                    model_class = apps.get_model(target_model)
                    created_instances = baker.make(model_class, _quantity=seed_count)

                    if not isinstance(created_instances, list):
                        created_instances = [created_instances]

                    seeded_info = [{"pk": obj.pk, "__str__": str(obj)} for obj in created_instances]
                return seeded_info

            # Only request construction + view execution runs inside the interceptor.
            def _sandbox_execution():
                if method in {"POST", "PUT", "PATCH"} and data is not None:
                    request = request_func(resolved_path, data=json.dumps(data), content_type=content_type)
                else:
                    request = request_func(resolved_path, data=query_params if method == "GET" else (data or {}))

                request.user = user if user is not None else AnonymousUser()
                request.resolver_match = resolved_match

                response = resolved_match.func(request, *resolved_match.args, **resolved_match.kwargs)

                if isinstance(response, Response) and hasattr(response, "render"):
                    response.render()

                return response

            # Execute the view wrapped in our DB-driver interceptor; seeding runs first, inside the same rollback boundary, outside the interceptor.
            response, queries_captured, db_duration, seeded_records_info = self.profile_callable(
                _sandbox_execution, setup=_seed
            )
            seeded_records_info = seeded_records_info or []
            status_code = getattr(response, "status_code", 200)
            response_body = self._parse_response_body(response)

        except Exception as e:
            return ExecutionResult(
                route=resolved_path,
                status_code=500,
                error=f"Exception raised inside sandbox execution: {str(e)}",
                side_effect_warnings=side_effect_warnings,
            )

        total_duration = (time.perf_counter() - start_time) * 1000.0

        formatted_queries = []
        for q in queries_captured:
            sql_text = q["sql"]
            formatted_queries.append({
                "sql": sql_text,
                # NOTE: detect_n_plus_one() re-fingerprints internally from "sql" and never reads this key, kept here for the ExecutionResult payload returned to callers (e.g. the MCP layer, UI), not for the analyzer.
                "fingerprint": fingerprint(sql_text),
                "time_ms": q["time_ms"],
                "source_location": q.get("source_location"),
            })

        n_plus_one_groups = detect_n_plus_one(formatted_queries, threshold=3, relationships=relationships)
        analysis_payload = []
        for group in n_plus_one_groups:
            fp = group["fingerprint"]
            analysis_payload.append({
                "fingerprint": fp,
                "count": group["count"],
                "src_loc": group.get("src_loc"),
                "suggestion": group.get("suggestion"),
                "sample_queries": group.get("sample_queries", []),
            })

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

    def _parse_response_body(self, response: Any) -> Optional[Any]:
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
        """
        Uses the framework-agnostic AST scanner to safely detect side effects 
        without executing the code.
        """
        warnings = []
        try:
            source_code = inspect.getsource(view_func)
            filename = inspect.getfile(view_func)
            
            # 1. Spin up our AST scanner
            advisor = StaticASTAdvisor(source_code, filename=filename)
            findings = advisor.run()
            
            # 2. Extract just the warning messages for the ExecutionResult
            for finding in findings:
                if finding.get("type") == "BLOCKING_EXTERNAL_CALL":
                    warnings.append(finding["message"])
                    
        except (TypeError, OSError, Exception):
            pass
            
        return list(set(warnings))