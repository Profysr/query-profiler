import traceback
from typing import Any, Dict, List, Optional, Tuple
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, Resolver404
from django.db import transaction
from django.urls import resolve, reverse
from model_bakery import baker
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from dqs.core.profiler import SQLProfiler
from dqs.core.analyzer import SQLAnalyzer

class SandboxRunner:
    """
    Robust execution sandbox for DQS. 
    Guarantees database isolation via savepoints, captures real primary keys from 
    seeded mock data, and profiles execution using SQLProfiler and SQLAnalyzer.
    """
    def __init__(self):
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DQS SandboxRunner can only run when DEBUG=True.")
        self.factory = APIRequestFactory()

    def run_profile(
        self,
        url_name: str,
        method: str = "GET",
        path_params: Optional[Dict[str, Any]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        seed_count: int = 0,
        target_model: Optional[str] = None,
        user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        
        path_params = path_params or {}
        query_params = query_params or {}
        http_method = method.lower()

        # 1. Open isolated transaction savepoint
        with transaction.atomic():
            sid = transaction.savepoint()
            seeded_records_info = []
            try:
                # 2. Seed mock records and capture their real primary keys
                if seed_count > 0 and target_model:
                    model_class = apps.get_model(target_model)
                    created_instances = baker.make(model_class, _quantity=seed_count)
                    if not isinstance(created_instances, list):
                        created_instances = [created_instances]
                    
                    seeded_records_info = [
                        {"pk": obj.pk, "__str__": str(obj)} for obj in created_instances
                    ]

                # 3. Resolve execution path natively via Django reverse()
                try:
                    formatted_path = reverse(url_name, kwargs=path_params)
                except Exception as rev_err:
                    return {
                        "status_code": 400,
                        "error": f"URL Reversal Failed: {str(rev_err)}",
                        "queries": [],
                        "total_queries": 0,
                        "n_plus_one_detected": False,
                    }

                # 4. Construct DRF Request with user context
                request_func = getattr(self.factory, http_method)
                if http_method == "get":
                    request = request_func(formatted_path, data=query_params)
                else:
                    request = request_func(formatted_path, data=payload or {}, format="json")

                request.user = user or AnonymousUser()

                # 5. Resolve view & handle routing errors gracefully
                try:
                    resolved = resolve(formatted_path)
                except Resolver404:
                    return {
                        "status_code": 404,
                        "error": f"Resolved path '{formatted_path}' returned Resolver404.",
                        "queries": [],
                        "total_queries": 0,
                        "n_plus_one_detected": False,
                    }

                view_func = resolved.func
                request.resolver_match = resolved

                # 6. Execute, profile SQL queries, and capture responses safely
                with SQLProfiler() as profiler:
                    try:
                        response = view_func(request, *resolved.args, **resolved.kwargs)
                        if isinstance(response, Response) and hasattr(response, "render"):
                            response.render()
                    except Exception as view_err:
                        return {
                            "status_code": 500,
                            "error": str(view_err),
                            "traceback": traceback.format_exc(),
                            "queries": profiler.captured_queries,
                            "total_queries": len(profiler.captured_queries),
                            "n_plus_one_detected": False,
                        }

                # 7. Analyze queries using SQLAnalyzer (N+1 detection & fingerprints)
                analysis_results = SQLAnalyzer.analyze(profiler.captured_queries)

                return {
                    "status_code": getattr(response, "status_code", 200),
                    "response_content": getattr(response, "data", getattr(response, "content", None)),
                    "seeded_records": seeded_records_info,
                    "queries": profiler.captured_queries,
                    "total_queries": len(profiler.captured_queries),
                    "n_plus_one_detected": analysis_results.get("has_n_plus_one", False),
                    "optimization_suggestions": analysis_results.get("suggestions", []),
                }

            finally:
                # 8. Absolute rollback guarantee: database remains completely pristine
                transaction.savepoint_rollback(sid)