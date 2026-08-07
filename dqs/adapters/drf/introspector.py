"""
=============================================================================
ELI5 FLOW MAP (How DjangoIntrospector works step-by-step):
=============================================================================
1. list_all_routes() 
   └── Calls -> _extract_patterns() [Crawls all website URLs like a tree]
       └── Calls -> _analyze_view() [Inspects if a URL points to a DRF API View]
             ├── Calls -> _extract_model_from_class() [Finds which database table it uses]
             └── Calls -> _extract_path_params() [Finds variables in the URL like id/pk]
=============================================================================
"""

"""
=============================================================================
Output Structure
=============================================================================
`[
  {
    "path": "/api/books/",
    "methods": ["GET", "POST"],
    "view_name": "book-list-create",
    "view_type": "DRF_ViewSet",
    "is_drf": true,
    "executable": true,
    "path_params": [],
    "target_model": "library.Book",
    "reason_unexecutable": null
  },
  {
    "path": "/api/books/{pk}/",
    "methods": ["GET", "PUT", "PATCH", "DELETE"],
    "view_name": "book-detail",
    "view_type": "DRF_ViewSet",
    "is_drf": true,
    "executable": true,
    "path_params": [
      {
        "name": "pk",
        "converter": "int"
      }
    ],
    "target_model": "library.Book",
    "reason_unexecutable": null
  }
]`
"""
import inspect
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Type
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, URLResolver, get_resolver
from django.urls.resolvers import RoutePattern, RegexPattern
from .types import PathParam, RouteMetadata
from .converters import PathConverterResolver

# Ensure DRF is present
try:
    from rest_framework.views import APIView
except ImportError:
    APIView = None

logger = logging.getLogger(__name__)
VALID_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

class DjangoIntrospector:
    """
    Safely scans Django URL routes to discover DRF APIs, extracts target database models,
    and maps URL route parameters without unsafe code execution.
    """

    def __init__(self):
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DjangoIntrospector can only run when DEBUG=True.")
        self.resolver = get_resolver()

    def list_all_routes(self) -> List[RouteMetadata]:
        routes: List[RouteMetadata] = []
        self._extract_patterns(self.resolver.url_patterns, prefix="/", routes=routes)
        return routes

    def _extract_patterns(self, patterns: List[Any], prefix: str, routes: List[RouteMetadata]) -> None:
        for pattern in patterns:
            # 1. Clean the path for both Resolvers (folders) and Patterns (endpoints)
            full_path = self._get_clean_path(pattern, prefix)
            
            # It's a folder (like include('api.urls')), go deeper using the cleaned prefix
            if isinstance(pattern, URLResolver):
                self._extract_patterns(pattern.url_patterns, full_path, routes)
                
            # It's an endpoint. Exclude internal dashboard routes
            elif isinstance(pattern, URLPattern):
                if full_path.startswith("/dqs/"):
                    continue

                # Analyze the view using the beautiful, clean path
                route_meta = self._analyze_view(pattern, full_path)
                if route_meta:
                    routes.append(route_meta)

    def _get_clean_path(self, pattern: Any, prefix: str) -> str:
        """
        Extracts the cleanest possible URL route, handling both Django's modern path()
        and DRF's legacy regex-based routers for both Resolvers and Patterns.
        """
        # 1. Handled by Django's modern path() - zero manipulation needed
        if isinstance(pattern.pattern, RoutePattern):
            route = str(pattern.pattern) 
            
        # 2. Handled by DRF Routers or explicit re_path() - Legacy
        elif isinstance(pattern.pattern, RegexPattern):
            raw_regex = str(pattern.pattern)
            route = re.sub(r"\(\?P<(\w+)>.*?\)", r"<\1>", raw_regex)  # Convert named groups to <param>
            route = route.lstrip("^").rstrip("$").replace("\\.", ".")
        else:
            # Fallback for unknown custom patterns
            route = str(pattern.pattern)

        # Safely join the prefix and the route
        combined = f"{prefix}/{route}".replace("//", "/")
        
        # Ensure it always starts with exactly one slash, but doesn't double up
        return "/" + combined.strip("/")

    def _extract_model_from_class(self, view_class: Type) -> Optional[str]:
        """Inspect class attributes static metadata without instantiating or executing code."""
        try:
            # 1. Direct Queryset
            queryset = getattr(view_class, "queryset", None)
            if queryset is not None and hasattr(queryset, "model"):
                model = queryset.model
                return f"{model._meta.app_label}.{model._meta.object_name}"

            # 2. Direct Model
            model = getattr(view_class, "model", None)
            if model and hasattr(model, "_meta"):
                return f"{model._meta.app_label}.{model._meta.object_name}"

            # 3. Serializer Class Meta Model
            serializer_cls = getattr(view_class, "serializer_class", None)
            if serializer_cls and hasattr(serializer_cls, "Meta"):
                meta_model = getattr(serializer_cls.Meta, "model", None)
                if meta_model and hasattr(meta_model, "_meta"):
                    return f"{meta_model._meta.app_label}.{meta_model._meta.object_name}"

            # SAFE Static Analysis for get_queryset return type hint if available
            if hasattr(view_class, "get_queryset"):
                return_type = inspect.signature(view_class.get_queryset).return_annotation
                if return_type and hasattr(return_type, "model"):
                    m = return_type.model
                    return f"{m._meta.app_label}.{m._meta.object_name}"

        except Exception as e:
            logger.debug("Model extraction failed for %s: %s", view_class, e)

        return None

    def _extract_path_params(self, pattern: URLPattern) -> List[PathParam]:
        try:
            return PathConverterResolver.extract_converters_from_pattern(pattern)
        except Exception as e:
            logger.warning("Failed to extract path params for %s: %s", pattern, e)
            return []

    def _analyze_view(self, pattern: URLPattern, full_path: str) -> Optional[RouteMetadata]:
        callback = pattern.callback
        if not callable(callback):
            return None

        unwrapped_callback = inspect.unwrap(callback)

        view_class: Optional[Type] = (
            getattr(callback, "view_class", None)
            or getattr(callback, "cls", None)
            or getattr(unwrapped_callback, "view_class", None)
            or getattr(unwrapped_callback, "cls", None)
        )

        if view_class is None or APIView is None or not issubclass(view_class, APIView):
            return None

        target_model = self._extract_model_from_class(view_class)
        path_params = self._extract_path_params(pattern)

        # Handle ViewSet Actions vs Regular APIViews
        if hasattr(callback, "actions"):
            actions: dict = getattr(callback, "actions", {})
            methods = [m.upper() for m in actions.keys() if m.upper() in VALID_HTTP_METHODS]
            executable = len(methods) > 0
            reason = None if executable else "Could not resolve ViewSet actions mapping."
            view_type = "DRF_ViewSet"
        else:
            methods = [
                m.upper() for m in getattr(view_class, "http_method_names", [])
                if hasattr(view_class, m) and m.upper() in VALID_HTTP_METHODS
            ]
            executable = len(methods) > 0
            reason = None if executable else "Could not resolve http_method_names."
            view_type = "DRF_APIView"

        return RouteMetadata(
            path=full_path,
            methods=methods if executable else [],
            view_name=pattern.name or view_class.__name__,
            view_type=view_type,
            executable=executable,
            path_params=path_params,
            target_model=target_model,
            reason_unexecutable=reason,
            view_callable=view_class,
        )