import datetime
import decimal
import json
import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from dqs.adapters.drf.execution.runner import DjangoSandboxRunner
from dqs.adapters.drf.routing.introspector import DjangoIntrospector

# ---------------------------------------------------------------------------
# Helpers & Security Guardrails
# ---------------------------------------------------------------------------
def require_debug(is_ajax: bool = False):
    """
    View decorator that short-circuits with HTTP 403 when DEBUG=False.
    Returns JSON for AJAX endpoints and plain text/HTML for template views.
    """
    def decorator(view_func):
        def _wrapper(request, *args, **kwargs):
            if not getattr(settings, "DEBUG", False):
                msg = (
                    "Da Profiler is disabled in production. "
                    "Set DEBUG=True in local settings."
                )
                if is_ajax or request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"error": msg}, status=403)
                return HttpResponseForbidden(msg)
            return view_func(request, *args, **kwargs)
        return _wrapper
    return decorator


class DQSJSONEncoder(DjangoJSONEncoder):
    """
    Extends Django's native encoder to safely serialize byte streams,
    ORM instances, and fallback object representations.
    """
    def default(self, obj: Any) -> Any:
        if isinstance(obj, bytes):
            try:
                return obj.decode("utf-8")
            except UnicodeDecodeError:
                return repr(obj)
        if hasattr(obj, "_meta") or hasattr(obj, "__dict__"):
            return str(obj)
        try:
            return super().default(obj)
        except TypeError:
            return repr(obj)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
class DQSDashboardView(View):
    """Renders the Da Profiler developer dashboard (GET /dqs/)."""

    @method_decorator(require_debug(is_ajax=False))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):

        try:
            introspector = DjangoIntrospector()
            routes = introspector.list_all_routes()
        except ImproperlyConfigured as exc:
            return HttpResponseForbidden(str(exc))

        # Leverage model/dataclass .to_dict() if present, or clean map
        routes_data = [
            r.to_dict() if hasattr(r, "to_dict") else r.__dict__ 
            for r in routes
        ]

        return render(request, "dqs/dashboard.html", {
            "routes": routes_data,
            "routes_json": json.dumps(routes_data, cls=DQSJSONEncoder),
            "routes_count": len(routes_data),
        })


class DQSProfileView(View):
    """AJAX profiling endpoint (POST /dqs/profile/)."""

    @method_decorator(require_debug(is_ajax=True))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        route = body.get("route")
        if not route:
            return JsonResponse({"error": "'route' is required."}, status=400)

        method = str(body.get("method", "GET")).upper()
        seed_count = max(0, int(body.get("seed_count") or 0))
        path_params = body.get("path_params") or {}
        target_model = body.get("target_model") or None

        try:
            runner = DjangoSandboxRunner()
            result = runner.execute_isolated(
                url_name_or_path=route,
                method=method,
                path_params=path_params,
                seed_count=seed_count,
                target_model=target_model,
            )
        except ImproperlyConfigured as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": f"Sandbox execution failed: {exc}"},
                status=500,
            )

        result_dict = result.to_dict() if hasattr(result, "to_dict") else result.__dict__
        return JsonResponse(result_dict, encoder=DQSJSONEncoder)