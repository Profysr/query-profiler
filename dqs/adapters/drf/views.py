from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dqs.adapters.drf.execution.runner import DjangoSandboxRunner
from dqs.adapters.drf.routing.introspector import DjangoIntrospector


# ---------------------------------------------------------------------------
# Helpers & Security Guardrails
# ---------------------------------------------------------------------------
def require_debug(view_func):
    """
    Decorator that short-circuits with HTTP 403 when DEBUG=False.
    Returns JSON response.
    """
    def _wrapper(self, request, *args, **kwargs):
        if not getattr(settings, "DEBUG", False):
            msg = (
                "Da Profiler is disabled in production. "
                "Set DEBUG=True in local settings."
            )
            return Response({"error": msg}, status=status.HTTP_403_FORBIDDEN)
        return view_func(self, request, *args, **kwargs)
    return _wrapper


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


def _serialize_route(route) -> dict[str, Any]:
    """Serialize RouteMetadata to dict."""
    data = route.__dict__.copy()
    # Convert path_params to serializable format
    if "path_params" in data:
        data["path_params"] = [
            {"name": p.name, "converter": p.converter} for p in data["path_params"]
        ]
    # Remove non-serializable fields
    data.pop("view_callable", None)
    return data


# ---------------------------------------------------------------------------
# API Views
# ---------------------------------------------------------------------------
class DQSDashboardView(APIView):
    """API endpoint to list all discoverable routes (GET /dqs/)."""
    authentication_classes = []
    permission_classes = []

    @require_debug
    def get(self, request: Request) -> Response:
        try:
            introspector = DjangoIntrospector()
            routes = introspector.list_all_routes()
        except ImproperlyConfigured as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        routes_data = [_serialize_route(r) for r in routes]

        return Response({
            "routes": routes_data,
            "count": len(routes_data),
        })


class DQSProfileView(APIView):
    """API endpoint to profile a specific route (POST /dqs/profile/)."""
    authentication_classes = []
    permission_classes = []

    @require_debug
    def post(self, request: Request) -> Response:
        # DRF parses JSON automatically
        body = request.data

        route = body.get("route")
        if not route:
            return Response({"error": "'route' is required."}, status=status.HTTP_400_BAD_REQUEST)

        method = str(body.get("method", "GET")).upper()
        seed_count = max(0, int(body.get("seed_count") or 0))
        path_params = body.get("path_params") or {}
        target_model = body.get("target_model") or None
        relationships = body.get("relationships") or None

        try:
            runner = DjangoSandboxRunner()
            result = runner.execute_isolated(
                url_name_or_path=route,
                method=method,
                path_params=path_params,
                seed_count=seed_count,
                target_model=target_model,
                relationships=relationships,
            )
        except ImproperlyConfigured as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"error": f"Sandbox execution failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Serialize ExecutionResult
        result_dict = result.__dict__.copy()
        return Response(result_dict)


class DQSHealthView(APIView):
    """Health check endpoint (GET /dqs/health/)."""
    authentication_classes = []
    permission_classes = []

    @require_debug
    def get(self, request: Request) -> Response:
        from dqs.adapters.drf.router import SHADOW_DB_ALIAS

        shadow_configured = SHADOW_DB_ALIAS in getattr(settings, "DATABASES", {})
        router_configured = "dqs.adapters.drf.router.DQSRouter" in getattr(settings, "DATABASE_ROUTERS", [])

        return Response({
            "status": "ok",
            "debug": getattr(settings, "DEBUG", False),
            "shadow_db_configured": shadow_configured,
            "router_configured": router_configured,
            "shadow_db_alias": SHADOW_DB_ALIAS,
        })