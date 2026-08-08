"""
Django Introspector & Route Discovery (dqs/adapters/drf/routing/introspector.py)
================================================================================
Scans Django URL routes to discover DRF APIs, target models, path parameters,
and view lookup mappings (lookup_field / lookup_url_kwarg).
"""

# =============================================================================
# Step 01 - Imports, Logger & Constant Configuration
# =============================================================================
import inspect
import logging
import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, URLResolver, get_resolver
from django.urls.resolvers import RegexPattern, RoutePattern
from dqs.adapters.drf.routing.converters import PathConverterResolver
from dqs.adapters.drf.types import PathParam, RouteMetadata

try:
    from rest_framework.views import APIView
except ImportError:
    APIView = None

logger = logging.getLogger(__name__)

# Primary HTTP verbs used to evaluate route executability
CORE_HTTP_METHODS: set[str] = {"GET", "POST", "PUT", "PATCH", "DELETE"}
VALID_HTTP_METHODS: set[str] = CORE_HTTP_METHODS | {"HEAD", "OPTIONS"}


# =============================================================================
# Step 02 - Introspector Initialization & Debug Safety Guard
# =============================================================================
class DjangoIntrospector:
    """
    Safely scans Django URL routes to discover DRF APIs, extracts target database models,
    and maps URL route parameters without unsafe code execution.
    """

    def __init__(self):
        # Step 02.1 - Safety check: Prevent execution in non-debug production environments
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DjangoIntrospector can only run when DEBUG=True.")
        self.resolver = get_resolver()

    # =========================================================================
    # Step 03 - URL Tree Traversal & Route Discovery Entry Point
    # =========================================================================
    def list_all_routes(self) -> list[RouteMetadata]:
        """Step 03.1 - Public entry point: Recursively scans root URL patterns."""
        routes: list[RouteMetadata] = []
        self._extract_patterns(self.resolver.url_patterns, prefix="/", routes=routes)
        return routes

    def _extract_patterns(self, patterns: list[Any], prefix: str, routes: list[RouteMetadata]) -> None:
        """Step 03.2 - Recursive URL pattern tree walker handling resolvers and leaves."""
        for pattern in patterns:
            full_path = self._get_clean_path(pattern, prefix)

            if isinstance(pattern, URLResolver):
                self._extract_patterns(pattern.url_patterns, full_path, routes)

            elif isinstance(pattern, URLPattern):
                # Ignore internal profiling / diagnostic routes
                if full_path.startswith("/dqs/"):
                    continue

                route_meta = self._analyze_view(pattern, full_path)
                if route_meta:
                    routes.append(route_meta)

    # =========================================================================
    # Step 04 - Path Normalization & Regex Sanitization
    # =========================================================================
    def _get_clean_path(self, pattern: Any, prefix: str) -> str:
        """Step 04.1 - Converts RoutePattern or RegexPattern objects into clean path templates."""
        pattern_obj = getattr(pattern, "pattern", None)

        if isinstance(pattern_obj, RoutePattern):
            route = str(pattern_obj)

        elif isinstance(pattern_obj, RegexPattern):
            raw_regex = str(pattern_obj)
            # Convert named capture groups (?P<id>\d+) -> <id>
            route = re.sub(r"\(\?P<(\w+)>.*?\)", r"<\1>", raw_regex)
            # Clean common regex anchors, non-capturing groups, and optional slashes
            route = re.sub(r"\(\?:[^\)]+\)", "", route)
            route = route.lstrip("^").rstrip("$").replace("\\Z", "").replace("\\.", ".").replace("/?", "/")
        else:
            route = str(pattern_obj) if pattern_obj else ""

        combined = f"{prefix}/{route}".replace("//", "/")
        return "/" + combined.lstrip("/")

    # =========================================================================
    # Step 05 - Multi-Strategy Model Discovery Engine
    # =========================================================================
    def _extract_model_from_class(self, view_class: type) -> str | None:
        """
        Step 05.1 - Attempts to determine target Django Model from view attributes:
        1. Class static `queryset` attribute
        2. Class static `model` attribute
        3. Class static `serializer_class.Meta.model` attribute
        4. Dynamic `get_serializer_class()` class reference
        5. `get_queryset()` signature return annotations
        """
        try:
            # Strategy 1: Direct queryset attribute
            queryset = getattr(view_class, "queryset", None)
            if queryset is not None and hasattr(queryset, "model"):
                model = queryset.model
                return f"{model._meta.app_label}.{model._meta.object_name}"

            # Strategy 2: Direct model attribute
            model = getattr(view_class, "model", None)
            if model and hasattr(model, "_meta"):
                return f"{model._meta.app_label}.{model._meta.object_name}"

            # Strategy 3: Serializer Class Meta.model reference
            serializer_cls = getattr(view_class, "serializer_class", None)

            # Strategy 4: Dynamic get_serializer_class lookup if static attribute missing
            if not serializer_cls and hasattr(view_class, "get_serializer_class"):
                try:
                    serializer_cls = view_class.get_serializer_class(None)
                except Exception:
                    logger.debug("Could not inspect serializer class for %s", view_class)

            if serializer_cls and hasattr(serializer_cls, "Meta"):
                meta_model = getattr(serializer_cls.Meta, "model", None)
                if meta_model and hasattr(meta_model, "_meta"):
                    return f"{meta_model._meta.app_label}.{meta_model._meta.object_name}"

            # Strategy 5: Return annotation inspection on get_queryset
            if hasattr(view_class, "get_queryset"):
                try:
                    sig = inspect.signature(view_class.get_queryset)
                    return_type = sig.return_annotation
                    if return_type and hasattr(return_type, "model"):
                        m = return_type.model
                        return f"{m._meta.app_label}.{m._meta.object_name}"
                except (ValueError, TypeError):
                    pass

        except Exception as e:
            logger.debug("Model extraction failed for %s: %s", view_class, e)

        return None

    # =========================================================================
    # Step 06 - View Lookup Field Mapping Extraction
    # =========================================================================
    def _extract_view_lookup_map(self, view_class: type) -> dict[str, str]:
        """
        Step 06.1 - Extracts DRF lookup mapping for path parameters.
        e.g. lookup_field = "sha_256", lookup_url_kwarg = "hash" -> maps {"hash": "sha_256"}
        """
        lookup_map: dict[str, str] = {}
        lookup_field = getattr(view_class, "lookup_field", "pk")
        lookup_url_kwarg = getattr(view_class, "lookup_url_kwarg", None) or lookup_field

        if lookup_url_kwarg and lookup_field:
            lookup_map[lookup_url_kwarg] = lookup_field

        return lookup_map

    # =========================================================================
    # Step 07 - Path Parameter Extraction Engine (Route & Regex Fallbacks)
    # =========================================================================
    def _extract_path_params(self, pattern: URLPattern) -> list[PathParam]:
        """
        Step 07.1 - Extracts parameter metadata using PathConverterResolver with
        a fallback regex parser for re_path routes.
        """
        try:
            params = PathConverterResolver.extract_converters_from_pattern(pattern)
            if params:
                return params

            # Fallback for RegexPattern where converter maps are empty
            pattern_obj = getattr(pattern, "pattern", None)
            if isinstance(pattern_obj, RegexPattern):
                raw_regex = str(pattern_obj)
                param_names = re.findall(r"\(\?P<(\w+)>.*?\)", raw_regex)
                return [PathParam(name=p, converter="str") for p in param_names]

            return []
        except Exception as e:
            logger.warning("Failed to extract path params for %s: %s", pattern, e)
            return []

    # =========================================================================
    # Step 08 - DRF View & ViewSet Analysis Engine
    # =========================================================================
    def _analyze_view(self, pattern: URLPattern, full_path: str) -> RouteMetadata | None:
        """
        Step 08.1 - Analyzes URL callback to determine if it target a DRF APIView or ViewSet,
        validating supported HTTP methods and resolving metadata.
        """
        callback = pattern.callback
        if not callable(callback):
            return None

        unwrapped_callback = inspect.unwrap(callback)

        view_class: type | None = (
            getattr(callback, "view_class", None)
            or getattr(callback, "cls", None)
            or getattr(unwrapped_callback, "view_class", None)
            or getattr(unwrapped_callback, "cls", None)
        )

        if view_class is None or APIView is None or not issubclass(view_class, APIView):
            return None

        target_model = self._extract_model_from_class(view_class)
        path_params = self._extract_path_params(pattern)
        lookup_map = self._extract_view_lookup_map(view_class)

        # Step 08.2 - ViewSet Action Resolution vs APIView Method Resolution
        if hasattr(callback, "actions"):
            actions: dict = getattr(callback, "actions", {})
            methods = [m.upper() for m in actions if m.upper() in VALID_HTTP_METHODS]
            executable = len(methods) > 0
            reason = None if executable else "Could not resolve ViewSet actions mapping."
            view_type = "DRF_ViewSet"
        else:
            # Filter methods to ensure class overrides standard base APIView methods
            raw_methods = [
                m.upper() for m in getattr(view_class, "http_method_names", [])
                if hasattr(view_class, m) and m.upper() in VALID_HTTP_METHODS
            ]
            
            # Check for actual business logic handlers beyond base OPTIONS/HEAD
            has_core_handlers = any(m in CORE_HTTP_METHODS for m in raw_methods)
            methods = raw_methods if has_core_handlers else []
            
            executable = len(methods) > 0
            reason = None if executable else "No core HTTP method handlers (GET, POST, etc.) defined on view class."
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
            lookup_map=lookup_map,
        )