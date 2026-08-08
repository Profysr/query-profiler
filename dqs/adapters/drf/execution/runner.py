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
from collections.abc import Callable
from typing import Any

from django.apps import apps
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.urls import resolve
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from dqs.adapters.drf.mocking.generator import ModelBakeryGenerator, infer_request_body
from dqs.adapters.drf.routing.converters import PathConverterResolver
from dqs.adapters.drf.types import ExecutionResult, RouteMetadata, SeedDataRequiredError
from dqs.core.static_advisor import StaticASTAdvisor
from dqs.core.targets import Target
from dqs.adapters.drf.database.db_manager import ShadowDatabaseManager
from .query_interceptor import QueryAnalysisEngine, QueryInterceptor
from dqs.adapters.drf.router import DQSRouter

# dqs/analysis/ast_analyzer.py
class StaticAnalysisService:
    """Inspects target view source code AST to detect blocking calls and external side effects."""

    @staticmethod
    def detect_side_effects(view_func: Any) -> list[str]:
        """Safely scans source code AST without executing the callable."""
        warnings = []
        try:
            source_code = inspect.getsource(view_func)
            filename = inspect.getfile(view_func)

            advisor = StaticASTAdvisor(source_code, filename=filename)
            findings = advisor.run()

            for finding in findings:
                if finding.get("type") == "BLOCKING_EXTERNAL_CALL":
                    warnings.append(finding["message"])

        except (TypeError, OSError, Exception):
            pass

        return list(set(warnings))

# dqs/builders/request_spec_builder.py
class RequestSpecBuilder:
    """Builds Postman-style request contracts for MCP Agents and UI Clients."""

    @staticmethod
    def build(
        url_name_or_path: str,
        method: str,
        resolved_path: str,
        route_meta: Any,
        resolved_params: dict[str, Any],
        query_params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path_params_spec = [
            {
                "name": p.name,
                "converter": p.converter,
                "status": "RESOLVED" if p.name in resolved_params else "UNRESOLVED",
                "value": resolved_params.get(p.name),
            }
            for p in getattr(route_meta, "path_params", [])
        ]

        return {
            "route": url_name_or_path,
            "method": method.upper(),
            "resolved_url": resolved_path,
            "path_params": path_params_spec,
            "query_params": query_params or {},
            "body": data,
        }

# dqs/targets/target_executor.py
class TargetExecutor:
    """Handles execution and query capturing for Non-HTTP targets (Django Signals & Celery Tasks)."""

    _SIGNAL_MAP = {
        "post_save": post_save,
        "pre_save": pre_save,
        "post_delete": post_delete,
        "pre_delete": pre_delete,
    }

    def __init__(self, profile_callable: Callable):
        self.profile_callable = profile_callable

    def trigger_signal(self, target: Target) -> ExecutionResult:
        """Synthesizes model events to trigger Django signal receivers in an isolated transaction."""
        spec = target.trigger_spec or {}
        signal_name = spec.get("signal")
        sender_model_path = spec.get("sender_model")

        if not target.triggerable or not sender_model_path:
            return ExecutionResult(
                route=target.id,
                status_code=400,
                error="Signal target is not triggerable — missing sender model path.",
            )

        try:
            model_class = apps.get_model(sender_model_path)
        except Exception as e:
            return ExecutionResult(route=target.id, status_code=400, error=f"Could not resolve sender model: {e}")

        def _fire_signal():
            instances = ModelBakeryGenerator.generate(model_class, quantity=1, commit=True)
            instance = instances[0]

            if signal_name in ("post_delete", "pre_delete"):
                instance.delete()
                return {"action": "delete", "model": sender_model_path}
            
            return {"action": "save", "model": sender_model_path, "pk": instance.pk}

        result, queries_captured, db_duration, _ = self.profile_callable(_fire_signal)

        return QueryAnalysisEngine.build_result(
            route=target.id,
            status_code=200,
            queries_captured=queries_captured,
            db_duration=db_duration,
            total_duration=db_duration,
            response_body=result,
            seeded_records_info=[],
            side_effect_warnings=[],
        )

    def trigger_task(self, target: Target, *task_args, **task_kwargs) -> ExecutionResult:
        """Executes Celery tasks synchronously in-process to capture SQL queries."""
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

        return QueryAnalysisEngine.build_result(
            route=target.id,
            status_code=200,
            queries_captured=queries_captured,
            db_duration=db_duration,
            total_duration=db_duration,
            response_body=result,
            seeded_records_info=[],
            side_effect_warnings=[],
        )

"""
Django Sandbox Runner (dqs/sandbox_runner.py)
=============================================
Main orchestrator for isolated DRF route profiling, database query interception,
mock data seeding, and non-HTTP target execution.
"""

# =============================================================================
# Step 01 - Imports & Dependency Resolution
# =============================================================================
class DjangoSandboxRunner:
    """
    Orchestrates isolated DRF request execution, mock data seeding, SQL query interception,
    and performance profiling.
    """
    # =========================================================================
    # Step 0.1 - Deferred Model Helpers
    # =========================================================================
    def _get_user(self, user: Any | None = None) -> Any:
        """
        Lazily imports and returns AnonymousUser if no explicit user is provided.
        """
        if user is not None:
            return user
        from django.contrib.auth.models import AnonymousUser
        return AnonymousUser()

    # =========================================================================
    # Step 02 - Initialization & Settings Pre-check Verification
    # =========================================================================
    def __init__(self):
        """
        Validates user settings setup (Shadow DB & Router), executes pending shadow DB
        migrations, and sets up request utilities.
        """
        ShadowDatabaseManager.ensure_initialized()
        self.factory = APIRequestFactory()
        self.target_executor = TargetExecutor(self.profile_callable)

    # =========================================================================
    # Step 03 - Intercepted Sandbox Execution Boundary
    # =========================================================================
    def profile_callable(
        self,
        func: Callable,
        *args,
        setup: Callable[[], Any] | None = None,
        **kwargs,
    ) -> tuple[Any, list[dict[str, Any]], float, Any]:
        """
        Executes any callable inside a query-interception boundary.
        Uses shadow DB routing when active, or atomic savepoint rollback on default DB.
        """
        queries_captured = []
        db_duration = 0.0
        result = None
        setup_result = None

        if DQSRouter.is_active():
            # Shadow DB active -> Persist mutations inside shadow instance
            if setup is not None:
                setup_result = setup()

            with QueryInterceptor() as interceptor:
                db_start = time.perf_counter()
                result = func(*args, **kwargs)
                db_duration = (time.perf_counter() - db_start) * 1000.0
                queries_captured = interceptor.captured_queries
        else:
            # Fallback to default DB -> Strict atomic savepoint rollback
            with transaction.atomic():
                sid = transaction.savepoint()
                try:
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
    # Step 04 - Pipeline Entry 1: Route & Path Converter Resolution
    # =========================================================================
    def resolve_path_step(
        self,
        route_meta: Any,
        explicit_params: dict[str, Any] | None = None,
        lookup_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Resolves concrete URL paths and populates dynamic path parameters."""
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

    # =========================================================================
    # Step 05 - Pipeline Entry 2: Direct Route Probe
    # =========================================================================
    def probe_route_step(
        self,
        concrete_url: str,
        method: str = "GET",
        user: Any | None = None,
    ) -> dict[str, Any]:
        """Issues an un-intercepted request to verify route accessibility and status code."""
        try:
            resolved_match = resolve(concrete_url)
            request_func = getattr(self.factory, method.lower(), self.factory.get)
            request = request_func(concrete_url)
            request.user = self._get_user(user)
            request.resolver_match = resolved_match

            response = resolved_match.func(request, *resolved_match.args, **resolved_match.kwargs)
            status_code = getattr(response, "status_code", 500)

            return {"status_code": status_code, "exists": status_code < 400, "error": None}
        except Exception as e:
            return {"status_code": 404, "exists": False, "error": str(e)}

    # =========================================================================
    # Step 06 - Pipeline Entry 3: Mock Resource Seeding
    # =========================================================================
    def seed_resource_step(self, target_model: str, seed_count: int = 1) -> dict[str, Any]:
        """Seeds mock data records safely using ModelBakeryGenerator."""
        try:
            instances = ModelBakeryGenerator.generate(target_model, quantity=seed_count, commit=True)
            return {
                "status_code": 201,
                "seeded": True,
                "seeded_count": len(instances),
                "instances": [{"pk": obj.pk, "__str__": str(obj)} for obj in instances],
            }
        except SeedDataRequiredError as seed_err:
            return {"status_code": 400, "seeded": False, "error": str(seed_err)}
        except Exception as e:
            return {"status_code": 500, "seeded": False, "error": str(e)}

    # =========================================================================
    # Step 07 - Pipeline Entry 4: Isolated Route Profiling & Execution
    # =========================================================================
    def execute_isolated(
        self,
        url_name_or_path: str,
        method: str = "GET",
        path_params: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        user: Any | None = None,
        relationships: dict[str, str] | None = None,
        seed_count: int = 0,
        target_model: str | None = None,
        content_type: str = "application/json",
    ) -> ExecutionResult:
        """Executes a target endpoint within an isolated sandbox and returns metrics."""
        method = method.upper()
        path_params = path_params or {}
        query_params = query_params or {}

        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return ExecutionResult(route=url_name_or_path, status_code=400, error=f"Invalid HTTP method: {method}")

        from dqs.adapters.drf.router import profiling_session

        with profiling_session():
            seeded_records_info = []

            # Step 07.1 - Ensure minimum threshold model seeding
            if target_model:
                try:
                    seed_meta = ModelBakeryGenerator.ensure_capped_seeding(target_model)
                    if seed_meta.get("seeded_count", 0) > 0:
                        seeded_records_info = seed_meta.get("instances", [])
                        seed_count = 0
                except SeedDataRequiredError as seed_err:
                    return ExecutionResult(route=url_name_or_path, status_code=400, error=str(seed_err))

            # Step 07.2 - Resolve path converters and parameters
            route_meta = RouteMetadata(
                path=url_name_or_path,
                methods=[method],
                view_name=url_name_or_path if not url_name_or_path.startswith("/") else "",
                view_type="DRF_APIView",
                target_model=target_model,
            )

            try:
                resolved_path, resolved_params, _ = PathConverterResolver.build_executable_url(
                    route=route_meta,
                    explicit_params=path_params,
                    auto_generate_if_missing=True,
                )
            except SeedDataRequiredError as seed_err:
                return ExecutionResult(route=url_name_or_path, status_code=400, error=str(seed_err))

            # Step 07.3 - Build structured Request Spec contract
            request_spec = RequestSpecBuilder.build(
                url_name_or_path=url_name_or_path,
                method=method,
                resolved_path=resolved_path,
                route_meta=route_meta,
                resolved_params=resolved_params,
                query_params=query_params,
                data=data,
            )

            # Step 07.4 - Check for unresolved path parameters (Handover Rule)
            unresolved_names = [p["name"] for p in request_spec["path_params"] if p["status"] == "UNRESOLVED"]
            if unresolved_names:
                return ExecutionResult(
                    route=url_name_or_path,
                    status_code=400,
                    error=(
                        f"Unresolved path parameter(s): {', '.join(unresolved_names)}. "
                        f"Please provide explicit values in 'path_params' or seed target model '{target_model}'."
                    ),
                    request_spec=request_spec,
                )

            # Step 07.5 - Match URL pattern callable
            try:
                resolved_match = resolve(resolved_path)
            except Exception as e:
                return ExecutionResult(
                    route=resolved_path,
                    status_code=404,
                    error=f"Route resolution failed: {e!s}",
                    request_spec=request_spec,
                )

            request_func = getattr(self.factory, method.lower(), None)
            if not request_func:
                return ExecutionResult(route=resolved_path, status_code=405, error=f"Unsupported method: {method}")

            # Step 07.6 - AST static side-effect analysis
            side_effect_warnings = StaticAnalysisService.detect_side_effects(resolved_match.func)

            start_time = time.perf_counter()
            try:
                def _seed():
                    if seed_count > 0 and target_model:
                        created = ModelBakeryGenerator.generate(target_model, quantity=seed_count, commit=True)
                        return [{"pk": obj.pk, "__str__": str(obj)} for obj in created]
                    return []

                def _sandbox_execution():
                    request_data = data
                    if method in {"POST", "PUT", "PATCH"} and request_data is None:
                        request_data = infer_request_body(resolved_match.func)

                    if method in {"POST", "PUT", "PATCH"} and request_data is not None:
                        request = request_func(resolved_path, data=json.dumps(request_data), content_type=content_type)
                    else:
                        request = request_func(resolved_path, data=query_params if method == "GET" else (request_data or {}))

                    request.user = self._get_user(user)
                    request.resolver_match = resolved_match

                    response = resolved_match.func(request, *resolved_match.args, **resolved_match.kwargs)

                    if isinstance(response, Response) and hasattr(response, "render"):
                        response.render()

                    return response

                # Step 07.7 - Execute view wrapped inside QueryInterceptor
                response, queries_captured, db_duration, extra_seeded = self.profile_callable(
                    _sandbox_execution, setup=_seed
                )

                seeded_records_info.extend(extra_seeded or [])
                status_code = getattr(response, "status_code", 200)
                response_body = QueryAnalysisEngine.parse_response_body(response)

            except Exception as e:
                return ExecutionResult(
                    route=resolved_path,
                    status_code=500,
                    error=f"Exception raised inside sandbox execution: {e!s}",
                    side_effect_warnings=side_effect_warnings,
                )

            total_duration = (time.perf_counter() - start_time) * 1000.0

            # Step 07.8 - Format and return execution results
            return QueryAnalysisEngine.build_result(
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

    # =========================================================================
    # Step 08 - Non-HTTP Target Delegators (Signals & Celery Tasks)
    # =========================================================================
    def trigger_signal_target(self, target: Target) -> ExecutionResult:
        """Delegates Django signal triggering to TargetExecutor."""
        return self.target_executor.trigger_signal(target)

    def trigger_task_target(self, target: Target, *task_args, **task_kwargs) -> ExecutionResult:
        """Delegates Celery task execution to TargetExecutor."""
        return self.target_executor.trigger_task(target, *task_args, **task_kwargs)