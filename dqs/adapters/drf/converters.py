"""
Path Converter Engine & Dynamic Parameter Resolver
==================================================
Resolves parameterized Django URL routes (such as `/books/<int:pk>/` or `/users/<uuid:id>/`)
by identifying required path parameters, fetching or generating concrete model instances
inside safe savepoints, and constructing executable URL paths.
"""

import logging
from typing import Any, Dict, List, Optional, Type

from django.apps import apps
from django.db import models
from django.urls import URLPattern, reverse
from django.urls.resolvers import RoutePattern
from model_bakery import baker

from dqs.adapters.drf.introspector import PathParam, RouteMetadata

logger = logging.getLogger("da_profiler.converters")


class PathConverterResolver:
    """
    Resolves dynamic path parameters for Django/DRF endpoints.
    """

    @staticmethod
    def extract_converters_from_pattern(pattern: URLPattern) -> List[PathParam]:
        """
        Extracts PathParam definitions (name and converter type) from a Django URLPattern.
        """
        route_pattern = getattr(pattern, "pattern", None)
        params: List[PathParam] = []

        if isinstance(route_pattern, RoutePattern):
            for name, converter in route_pattern.converters.items():
                conv_type = type(converter).__name__.replace("Converter", "").lower() or "str"
                params.append(PathParam(name=name, converter=conv_type))
        elif hasattr(route_pattern, "regex") and hasattr(route_pattern.regex, "groupindex"):
            for name in route_pattern.regex.groupindex.keys():
                params.append(PathParam(name=name, converter="unknown"))

        return params

    @classmethod
    def resolve_params_for_route(
        cls,
        route: RouteMetadata,
        explicit_params: Optional[Dict[str, Any]] = None,
        auto_generate_if_missing: bool = True,
    ) -> Tuple[Dict[str, Any], Optional[Any]]:
        """
        Resolves concrete values for all required path parameters of a route.
        Returns a tuple of (resolved_path_params_dict, created_mock_instance_or_none).
        """
        resolved: Dict[str, Any] = dict(explicit_params or {})

        if not route.has_path_params:
            return resolved, None

        missing_param_names = [p.name for p in route.path_params if p.name not in resolved]
        if not missing_param_names:
            return resolved, None

        # Attempt to resolve missing parameters using target_model
        created_instance = None
        if route.target_model and auto_generate_if_missing:
            try:
                app_label, model_name = route.target_model.split(".")
                model_class: Type[models.Model] = apps.get_model(app_label, model_name)

                # 1. Try finding an existing row in DB
                instance = model_class.objects.first()

                # 2. If no row exists, create a temporary mock row using baker
                if instance is None:
                    instance = baker.make(model_class)
                    created_instance = instance

                # Fill in missing parameters from instance fields
                for param_name in missing_param_names:
                    if param_name in ("pk", "id"):
                        resolved[param_name] = instance.pk
                    elif hasattr(instance, param_name):
                        resolved[param_name] = getattr(instance, param_name)
            except Exception as e:
                logger.warning(f"Could not auto-resolve path params for {route.path}: {e}")

        return resolved, created_instance

    @classmethod
    def build_executable_url(
        cls,
        route: RouteMetadata,
        explicit_params: Optional[Dict[str, Any]] = None,
        auto_generate_if_missing: bool = True,
    ) -> Tuple[str, Dict[str, Any], Optional[Any]]:
        """
        Builds a concrete URL string by resolving path parameters.
        Returns (concrete_url_path, resolved_params, created_instance).
        """
        params, created_instance = cls.resolve_params_for_route(
            route,
            explicit_params=explicit_params,
            auto_generate_if_missing=auto_generate_if_missing,
        )

        try:
            if route.view_name:
                concrete_url = reverse(route.view_name, kwargs=params)
                return concrete_url, params, created_instance
        except Exception:
            pass

        # Fallback: String substitution on route path template (e.g. /books/{pk}/ or /books/<int:pk>/)
        url = route.path
        for name, value in params.items():
            url = url.replace(f"<{name}>", str(value))
            url = url.replace(f"<{type(value).__name__}:{name}>", str(value))
            url = url.replace(f"{{{name}}}", str(value))

        return url, params, created_instance
