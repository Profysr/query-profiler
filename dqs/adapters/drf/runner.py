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
import re
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
from dqs.adapters.drf.converters import PathConverterResolver
from dqs.adapters.drf.introspector import RouteMetadata
from django.db.models.signals import post_save, pre_save, post_delete, pre_delete
from dqs.core.targets import Target
from dqs.core.static_advisor import StaticASTAdvisor
from dqs.adapters.drf.body_inferrer import infer_request_body


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

    # =========================================================================
    # Step-Driven Agent Execution Pipeline (MCP Entries)
    # =========================================================================

    def resolve_path_step(
        self,
        route_meta: Any,
        explicit_params: Optional[Dict[str, Any]] = None,
        lookup_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Pipeline Entry 1: Resolves concrete URL path and parameter mapping.
        """
        concrete_url, resolved_params, created_instance = PathConverterResolver.build_executable_url(
            route=route_meta,
            explicit_params=explicit_params,
            auto_generate_if_missing=True,
            lookup_map=lookup_map,
        )
        return {
            "resolved_url": concrete_url,
            "params": resolved_params,
            "has_mock_instance": created_instance is not None,
            "created_instance_pk": getattr(created_instance, "pk", None) if created_instance else None,
        }

    def probe_route_step(
        self,
        concrete_url: str,
        method: str = "GET",
        user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Pipeline Entry 2: Issues an un-intercepted request to probe route existence/status code.
        """
        try:
            resolved_match = resolve(concrete_url)
            request_func = getattr(self.factory, method.lower(), self.factory.get)
            request = request_func(concrete_url)
            request.user = user if user is not None else AnonymousUser()
            request.resolver_match = resolved_match

            view_class = route_meta.view_class
            if view_class is None:
                raise RuntimeError("No view class found for route")
            if inspect.isclass(view_class):
                # Handle Class-Based Views
                # Call as_view to get a callable view function
                view_func = view_class.as_view()
                response = view_func(request, *resolved_match.args, **resolved_match.kwargs)
            else:
                # Handle Function-Based Views
                response = view_class(request, *resolved_match.args, **resolved_match.kwargs)
                
            status_code = getattr(response, "status_code", 500)
            return {"status_code": status_code, "exists": status_code < 400, "error": None}
        except Exception as e:
            return {"status_code": 404, "exists": False, "error": str(e)}

    def seed_resource_step(
        self,
        target_model: str,
        seed_count: int = 1,
    ) -> Dict[str, Any]:
        """
        Pipeline Entry 3: Seeds mock resources using ModelBakeryGenerator inside safe transaction boundaries.
        """
        try:
            from dqs.adapters.drf.mock_generator import ModelBakeryGenerator
            instances = ModelBakeryGenerator.generate(target_model, quantity=seed_count, commit=True)
            return {
                "status_code": 201,
                "seeded": True,
                "seeded_count": len(instances),
                "instances": [{"pk": obj.pk, "__str__": str(obj)} for obj in instances],
            }
        except Exception as e:
            return {"status_code": 500, "seeded": False, "error": str(e)}

    def profile_target_step(
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
        """
        Pipeline Entry 4: Final execution step wrapping target request inside QueryInterceptor.
        """
        return self.execute_isolated(
            url_name_or_path=url_name_or_path,
            method=method,
            path_params=path_params,
            query_params=query_params,
            data=data,
            user=user,
            relationships=relationships,
            seed_count=seed_count,
            target_model=target_model,
            content_type=content_type,
        )

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

        # Single canonical path resolution call delegating to PathConverterResolver
        route_meta = RouteMetadata(
            path=url_name_or_path,
            methods=[method],
            view_name=url_name_or_path if not url_name_or_path.startswith("/") else "",
            view_type="DRF_APIView",
            target_model=target_model,
        )
        resolved_path, resolved_params, _ = PathConverterResolver.build_executable_url(
            route=route_meta,
            explicit_params=path_params,
            auto_generate_if_missing=True,
        )

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
                    from dqs.adapters.drf.mock_generator import ModelBakeryGenerator
                    created_instances = ModelBakeryGenerator.generate(target_model, quantity=seed_count, commit=True)
                    seeded_info = [{"pk": obj.pk, "__str__": str(obj)} for obj in created_instances]
                return seeded_info

            # Only request construction + view execution runs inside the interceptor.
            def _sandbox_execution():
                request_data = data
                if method in {"POST", "PUT", "PATCH"} and request_data is None:
                    request_data = infer_request_body(resolved_match.func)

                if method in {"POST", "PUT", "PATCH"} and request_data is not None:
                    request = request_func(resolved_path, data=json.dumps(request_data), content_type=content_type)
                else:
                    request = request_func(resolved_path, data=query_params if method == "GET" else (request_data or {}))

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

        return self._build_execution_result(
            route=resolved_path,
            status_code=status_code,
            queries_captured=queries_captured,
            db_duration=db_duration,
            total_duration=total_duration,
            response_body=response_body,
            seeded_records_info=seeded_records_info,
            side_effect_warnings=side_effect_warnings,
            relationships=relationships,
        )

    # Maps a signal's string name (as stored in Target.trigger_spec) back to the actual Django Signal object needed to know which model event to fire.
    _SIGNAL_NAME_MAP = {
        "post_save": post_save,
        "pre_save": pre_save,
        "post_delete": post_delete,
        "pre_delete": pre_delete,
    }

    def trigger_signal_target(self, target: Target) -> ExecutionResult:
        """
        Synthesizes the model event a signal receiver listens for, so the
        receiver actually fires and its queries get captured — all inside
        the same rollback boundary as everything else.
        """
        spec = target.trigger_spec or {}
        signal_name = spec.get("signal")
        sender_model_path = spec.get("sender_model")

        if not target.triggerable or not sender_model_path:
            return ExecutionResult(
                route=target.id,
                status_code=400,
                error="Signal target is not triggerable — no resolvable sender model.",
            )

        try:
            model_class = apps.get_model(sender_model_path)
        except Exception as e:
            return ExecutionResult(route=target.id, status_code=400, error=f"Could not resolve sender model: {e}")

        def _fire_signal():
            # baker.make() naturally fires pre_save/post_save on creation.
            # For post_delete/pre_delete, create first (untracked by the interceptor via `setup` in the caller), then delete here so the delete signal and only the delete signal — is captured.
            if signal_name in ("post_delete", "pre_delete"):
                instance = baker.make(model_class)
                instance.delete()
                return {"action": "delete", "model": sender_model_path}
            else:
                instance = baker.make(model_class)
                return {"action": "save", "model": sender_model_path, "pk": instance.pk}

        result, queries_captured, db_duration, _ = self.profile_callable(_fire_signal)
        return self._build_execution_result(
            route=target.id,
            status_code=200,
            queries_captured=queries_captured,
            db_duration=db_duration,
            total_duration=db_duration,
            response_body=result,
            seeded_records_info=[],
            side_effect_warnings=[],
        )

    def trigger_task_target(self, target: Target, *task_args, **task_kwargs) -> ExecutionResult:
        """
        Calls a discovered Celery task directly in-process (not via the broker),
        so it runs synchronously inside the same interceptor + rollback boundary.
        """
        spec = target.trigger_spec or {}
        task_name = spec.get("task_name")

        try:
            from celery import current_app
            task_func = current_app.tasks.get(task_name)
        except ImportError:
            return ExecutionResult(route=target.id, status_code=400, error="Celery is not installed.")

        if task_func is None:
            return ExecutionResult(route=target.id, status_code=404, error=f"Task '{task_name}' not found in registry.")

        try:
            result, queries_captured, db_duration, _ = self.profile_callable(
                task_func.run, *task_args, **task_kwargs
            )
        except Exception as e:
            return ExecutionResult(route=target.id, status_code=500, error=f"Exception raised inside task: {e}")

        return self._build_execution_result(
            route=target.id,
            status_code=200,
            queries_captured=queries_captured,
            db_duration=db_duration,
            total_duration=db_duration,
            response_body=result,
            seeded_records_info=[],
            side_effect_warnings=[],
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

    def _build_execution_result(
        self,
        route: str,
        status_code: int,
        queries_captured: List[Dict[str, Any]],
        db_duration: float,
        total_duration: float,
        response_body: Any,
        seeded_records_info: List[Dict[str, Any]],
        side_effect_warnings: List[str],
        relationships: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """Shared formatting/N+1-analysis path for any trigger method (view, signal, task)."""
        formatted_queries = []
        for q in queries_captured:
            sql_text = q["sql"]
            formatted_queries.append({
                "sql": sql_text,
                "fingerprint": fingerprint(sql_text),
                "time_ms": q["time_ms"],
                "source_location": q.get("source_location"),
            })

        n_plus_one_groups = detect_n_plus_one(formatted_queries, threshold=3, relationships=relationships)
        analysis_payload = [
            {
                "fingerprint": group["fingerprint"],
                "count": group["count"],
                "source_location": group.get("source_location"),
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