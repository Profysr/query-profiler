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
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, Callable

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, URLResolver, get_resolver
from django.urls.resolvers import RoutePattern

VALID_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


@dataclass
class PathParam:
    name: str
    converter: str


@dataclass
class RouteMetadata:
    path: str
    methods: List[str]
    view_name: str
    view_type: str
    is_drf: bool = True
    executable: bool = True
    path_params: List[PathParam] = field(default_factory=list)
    target_model: Optional[str] = None
    reason_unexecutable: Optional[str] = None
    view_callable: Optional[Callable] = None

    @property
    def has_path_params(self) -> bool:
        return len(self.path_params) > 0


class DjangoIntrospector:
    """
    Scans Django URL routes to find valid Django REST Framework (DRF) APIs,
    extracts their database models, and maps out their required URL parameters.
    """
    def __init__(self):
        # Safety check: DQS should only ever run in local development mode
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DjangoIntrospector can only run when DEBUG=True.")
        self.resolver = get_resolver()

    def list_all_routes(self) -> List[RouteMetadata]:
        """Step 1: Starts crawling the root URL list of the entire project."""
        routes: List[RouteMetadata] = []
        self._extract_patterns(self.resolver.url_patterns, prefix="/", routes=routes)
        return routes

    def _extract_patterns(self, patterns: List[Any], prefix: str, routes: List[RouteMetadata]) -> None:
        """Step 2: Recursively walks through URL groups (resolvers) and individual URL endpoints."""
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                # If it's a folder of URLs (e.g., include('api.urls')), add its prefix and look inside
                nested_prefix = prefix + str(pattern.pattern)
                self._extract_patterns(pattern.url_patterns, nested_prefix, routes)
            elif isinstance(pattern, URLPattern):
                # Clean up regular expression symbols from old-school URL patterns
                pattern_str = re.sub(r"^\^", "", str(pattern.pattern))
                pattern_str = re.sub(r"\$$", "", pattern_str)
                raw_path = (prefix + pattern_str).replace("//", "/")
                full_path = raw_path.rstrip("?").replace("\\.", ".")
                
                # Ignore our own DQS dashboard routes to avoid infinite loops
                if full_path.startswith("/dqs/"):
                    continue

                # Step 3: Analyze the individual endpoint view function
                route_meta = self._analyze_view(pattern, full_path)
                if route_meta:
                    routes.append(route_meta)

    def _extract_path_params(self, pattern: URLPattern) -> List[PathParam]:
        """Extracts URL parameters from modern Django RoutePattern converters."""
        # Local import avoids circular dependency: converters.py imports PathParam/RouteMetadata from this module.
        from dqs.adapters.drf.converters import PathConverterResolver
        return PathConverterResolver.extract_converters_from_pattern(pattern)

    def _analyze_view(self, pattern: URLPattern, full_path: str) -> Optional[RouteMetadata]:
        """Step 3 (cont.): Inspects a specific view function to ensure it's a valid DRF API."""
        callback = pattern.callback
        if not callable(callback):
            return None

        try:
            unwrapped_callback = inspect.unwrap(callback)
        except Exception:
            unwrapped_callback = callback

        # Pull out the underlying view class
        view_class: Optional[Type] = (
            getattr(callback, "view_class", None)
            or getattr(callback, "cls", None)
            or getattr(unwrapped_callback, "view_class", None)
            or getattr(unwrapped_callback, "cls", None)
        )
        
        if view_class is None:
            return None
            
        # Extract the original callable for AST static analysis. 
        # Prefer the underlying view class for DRF, fallback to the raw callback.
        original_callable = view_class if view_class else pattern.callback


        # Gate: Ignore non-DRF views (plain Django views)
        is_drf = any("rest_framework" in f"{base.__module__}.{base.__name__}" for base in inspect.getmro(view_class))
        if not is_drf:
            return None

        # Step 4: Extract model and path parameters
        target_model = self._extract_model_from_class(view_class)
        path_params = self._extract_path_params(pattern)

        # Determine HTTP methods allowed (GET, POST, etc.)
        if hasattr(view_class, "get_queryset") and hasattr(callback, "actions"):
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
            reason = None if executable else "Could statically resolve http_method_names."
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
            view_callable=original_callable,
        )

    def extract_view_lookup_map(self, view_class: Optional[Type]) -> Dict[str, str]:
        """
        Inspects DRF view class for lookup_url_kwarg and lookup_field mappings
        (e.g., article_slug -> slug, or pk -> id).
        """
        if view_class is None:
            return {}

        lookup_field = getattr(view_class, "lookup_field", "pk")
        lookup_url_kwarg = getattr(view_class, "lookup_url_kwarg", None) or lookup_field
        
        # Maps the parameter name as it appears in the URL to the model field name
        return {lookup_url_kwarg: lookup_field}

    def _extract_model_from_class(self, view_class: Type) -> Optional[str]:
        """Step 4 (cont.): Figures out which database model this view talks to."""
        try:
            # 1. Check direct queryset attribute
            queryset = getattr(view_class, "queryset", None)
            if queryset is not None and hasattr(queryset, "model"):
                model = queryset.model
                return f"{model._meta.app_label}.{model._meta.object_name}"

            # 2. Check direct model attribute
            model = getattr(view_class, "model", None)
            if model and hasattr(model, "_meta"):
                return f"{model._meta.app_label}.{model._meta.object_name}"

            # 3. Check serializer definition
            serializer_cls = getattr(view_class, "serializer_class", None)
            if serializer_cls and hasattr(serializer_cls, "Meta"):
                meta_model = getattr(serializer_cls.Meta, "model", None)
                if meta_model and hasattr(meta_model, "_meta"):
                    return f"{meta_model._meta.app_label}.{meta_model._meta.object_name}"

            # 4. Fallback: Safely evaluate dynamic get_queryset() methods using a mock request
            if hasattr(view_class, "get_queryset"):
                from django.test import RequestFactory
                from django.contrib.auth.models import AnonymousUser
                factory = RequestFactory()
                dummy_request = factory.get("/")
                dummy_request.user = AnonymousUser()
                
                instance = view_class()
                instance.request = dummy_request
                instance.args = ()
                instance.kwargs = {}
                qs = instance.get_queryset()
                if hasattr(qs, "model"):
                    m = qs.model
                    return f"{m._meta.app_label}.{m._meta.object_name}"
        except Exception:
            pass
            
        return None