import inspect
from dataclasses import dataclass, field
from typing import Any, List, Optional, Type
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, URLResolver, get_resolver

# Standard HTTP methods supported by Web standards
VALID_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

@dataclass
class RouteMetadata:
    path: str
    methods: List[str]
    view_name: str
    view_type: str  # 'FBV', 'CBV', 'DRF_APIView', 'DRF_ViewSet'
    is_drf: bool = False
    executable: bool = True
    has_path_params: bool = False
    target_model: Optional[str] = None


class DjangoIntrospector:
    def __init__(self):
        # Security Guardrail: Strictly enforce DEBUG environment boundary
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DjangoIntrospector can only run when DEBUG=True.")
        self.resolver = get_resolver()

    def list_all_routes(self) -> List[RouteMetadata]:
        """
        Recursively walks the Django URL tree and returns safe, structured metadata
        for all registered routes.
        """
        routes: List[RouteMetadata] = []
        self._extract_patterns(self.resolver.url_patterns, prefix="/", routes=routes)
        return routes

    def _extract_patterns(self, patterns: List[Any], prefix: str, routes: List[RouteMetadata]) -> None:
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                # Recurse into included URLconfs
                nested_prefix = prefix + str(pattern.pattern)
                self._extract_patterns(pattern.url_patterns, nested_prefix, routes)

            elif isinstance(pattern, URLPattern):
                # Clean path formatting
                full_path = (prefix + str(pattern.pattern)).replace("//", "/")

                # Exclude DQS internal endpoints to prevent recursion
                if full_path.startswith("/dqs/"):
                    continue

                route_meta = self._analyze_view(pattern, full_path)
                if route_meta:
                    routes.append(route_meta)

    def _analyze_view(self, pattern: URLPattern, full_path: str) -> Optional[RouteMetadata]:
        """
        Safely unwraps and inspects a view callback without invoking side effects.
        """
        callback = pattern.callback
        if not callable(callback):
            return None

        # Step 1: Safely unwrap all decorator layers
        try:
            unwrapped_callback = inspect.unwrap(callback)
        except Exception:
            unwrapped_callback = callback

        view_class: Optional[Type] = getattr(callback, "view_class", getattr(unwrapped_callback, "cls", None))
        has_path_params = "<" in full_path or "(?P" in full_path

        # Case A: DRF ViewSet / ModelViewSet
        if view_class and hasattr(view_class, "get_queryset") and hasattr(callback, "actions"):
            actions: dict = getattr(callback, "actions", {})
            methods = [method.upper() for method in actions.keys() if method.upper() in VALID_HTTP_METHODS]
            target_model = self._extract_model_from_class(view_class)

            return RouteMetadata(
                path=full_path,
                methods=methods or ["GET"],
                view_name=pattern.name or view_class.__name__,
                view_type="DRF_ViewSet",
                is_drf=True,
                executable=True,
                has_path_params=has_path_params,
                target_model=target_model,
            )

        # Case B: DRF APIView or Django CBV
        if view_class or (inspect.isclass(unwrapped_callback) and hasattr(unwrapped_callback, "as_view")):
            target_class = view_class or unwrapped_callback
            is_drf = hasattr(target_class, "rest_framework") or any(
                "rest_framework" in f"{base.__module__}.{base.__name__}"
                for base in inspect.getmro(target_class)
            )

            # Discover implemented HTTP methods statically
            allowed_methods = []
            http_method_names = getattr(target_class, "http_method_names", ["get", "post", "put", "patch", "delete"])
            for method in http_method_names:
                if hasattr(target_class, method) and method.upper() in VALID_HTTP_METHODS:
                    allowed_methods.append(method.upper())

            target_model = self._extract_model_from_class(target_class)

            return RouteMetadata(
                path=full_path,
                methods=allowed_methods or ["GET"],
                view_name=pattern.name or target_class.__name__,
                view_type="DRF_APIView" if is_drf else "CBV",
                is_drf=is_drf,
                executable=True,
                has_path_params=has_path_params,
                target_model=target_model,
            )

        # Case C: Function-Based Views (FBV)
        allowed_methods = []

        # Check Django @require_http_methods or DRF @api_view
        if hasattr(callback, "_allowed_methods"):
            allowed_methods = [m.upper() for m in getattr(callback, "_allowed_methods") if m.upper() in VALID_HTTP_METHODS]
        elif hasattr(unwrapped_callback, "_allowed_methods"):
            allowed_methods = [m.upper() for m in getattr(unwrapped_callback, "_allowed_methods") if m.upper() in VALID_HTTP_METHODS]

        # Check if wrapped by DRF @api_view
        is_drf = hasattr(callback, "cls") or hasattr(unwrapped_callback, "cls")

        return RouteMetadata(
            path=full_path,
            methods=allowed_methods or ["GET", "POST"],  # Default fallback for unannotated FBVs
            view_name=pattern.name or unwrapped_callback.__name__,
            view_type="FBV",
            is_drf=is_drf,
            executable=True,
            has_path_params=has_path_params,
            target_model=None,  # FBVs require route token matching in v0.3.0
        )

    def _extract_model_from_class(self, view_class: Type) -> Optional[str]:
        """
        Safely reflects queryset or model attributes on a view class
        without executing database queries.
        """
        try:
            # Check for direct model attribute (e.g. model = Book)
            model = getattr(view_class, "model", None)
            if model and hasattr(model, "_meta"):
                return f"{model._meta.app_label}.{model._meta.object_name}"

            # Check for queryset attribute (e.g. queryset = Book.objects.all())
            queryset = getattr(view_class, "queryset", None)
            if queryset is not None and hasattr(queryset, "model"):
                return f"{queryset.model._meta.app_label}.{queryset.model._meta.object_name}"
        except Exception:
            # Ignore dynamic evaluation errors safely
            pass
        return None