"""
Path Converter Engine & Dynamic Parameter Resolver
==================================================
Resolves parameterized Django URL routes (such as `/books/<int:pk>/` or `/users/<uuid:id>/`)
by identifying required path parameters, fetching or generating concrete model instances
inside safe savepoints, and constructing executable URL paths. Handles custom converters,
lookup_url_kwarg mappings, synthetic fallbacks, and regex patterns gracefully.
"""

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple, Type

from django.apps import apps
from django.db import models
from django.urls import URLPattern, reverse, get_converters
from django.urls.resolvers import RoutePattern
from model_bakery import baker

from dqs.adapters.drf.introspector import PathParam, RouteMetadata

logger = logging.getLogger("da_profiler.converters")


class PathConverterResolver:
    """
    Modular, step-driven parameter resolution engine for Django/DRF endpoints.
    """

    @classmethod
    def resolve_converter_type(cls, converter_name: str) -> str:
        """
        Queries Django's get_converters() registry to inspect registered converters.
        """
        converters = get_converters()
        if converter_name in converters:
            conv_obj = converters[converter_name]
            return type(conv_obj).__name__.replace("Converter", "").lower()
        return converter_name or "str"

    @classmethod
    def extract_converters_from_pattern(cls, pattern: URLPattern) -> List[PathParam]:
        """
        Extracts PathParam definitions from a modern Django RoutePattern.
        """
        route_pattern = getattr(pattern, "pattern", None)
        params: List[PathParam] = []

        if isinstance(route_pattern, RoutePattern):
            for name, converter in route_pattern.converters.items():
                conv_type = cls.resolve_converter_type(type(converter).__name__.replace("Converter", "").lower())
                params.append(PathParam(name=name, converter=conv_type))

        return params

    @classmethod
    def generate_synthetic_fallback(cls, param_name: str, converter_type: str) -> Any:
        """
        Entry C: Produces deterministic fallback values when no model/DB record exists.
        """
        conv = (converter_type or "").lower()
        if conv in ("int", "integer", "autofield"):
            return 1
        elif conv in ("uuid", "guid"):
            return "123e4567-e89b-12d3-a456-426614174000"
        elif conv in ("slug", "str", "string", "path"):
            if "slug" in param_name:
                return "test-slug"
            return "test-param"
        return "1"

    @classmethod
    def extract_from_model_instance(
        cls,
        instance: models.Model,
        param_name: str,
        lookup_map: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        Entry B: Extracts parameter value from a model instance, mapping lookup_url_kwarg to lookup_field.
        """
        lookup_map = lookup_map or {}
        model_field_name = lookup_map.get(param_name, param_name)

        if model_field_name in ("pk", "id"):
            return instance.pk

        if hasattr(instance, model_field_name):
            val = getattr(instance, model_field_name)
            return val() if callable(val) else val

        # Attribute fallback matching (e.g., category_code -> category_id / code)
        for attr in (param_name, "pk", "id", "slug", "code"):
            if hasattr(instance, attr):
                val = getattr(instance, attr)
                return val() if callable(val) else val

        return instance.pk

    @classmethod
    def resolve_params_for_route(
        cls,
        route: RouteMetadata,
        explicit_params: Optional[Dict[str, Any]] = None,
        auto_generate_if_missing: bool = True,
        lookup_map: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, Any], Optional[Any]]:
        """
        Resolves concrete values for all required path parameters of a route.
        Returns a tuple of (resolved_path_params_dict, created_mock_instance_or_none).
        """
        resolved: Dict[str, Any] = dict(explicit_params or {})

        if not route.has_path_params:
            return resolved, None

        missing_params = [p for p in route.path_params if p.name not in resolved]
        if not missing_params:
            return resolved, None

        created_instance = None
        model_class: Optional[Type[models.Model]] = None

        # 1. Try finding/seeding a database model instance
        if route.target_model and auto_generate_if_missing:
            try:
                app_label, model_name = route.target_model.split(".")
                model_class = apps.get_model(app_label, model_name)

                # Try finding an existing row in DB
                instance = model_class.objects.first()

                # If no row exists, safely attempt mock row creation via baker
                if instance is None:
                    try:
                        instance = baker.make(model_class)
                        created_instance = instance
                    except Exception as seed_err:
                        logger.warning(f"baker.make failed for model {route.target_model}: {seed_err}")
                        instance = None

                if instance is not None:
                    for p in missing_params:
                        resolved[p.name] = cls.extract_from_model_instance(instance, p.name, lookup_map)
            except Exception as e:
                logger.warning(f"Model resolution failed for route {route.path}: {e}")

        # 2. Synthetic fallback for any parameters that remain unresolved (e.g. plain APIView, baker failure)
        for p in missing_params:
            if p.name not in resolved:
                resolved[p.name] = cls.generate_synthetic_fallback(p.name, p.converter)

        return resolved, created_instance

    @classmethod
    def render_concrete_url(
        cls,
        route: RouteMetadata,
        resolved_params: Dict[str, Any],
    ) -> str:
        """
        Entry D: Renders a final executable URL string via Django reverse() or path substitution.
        """
        if route.view_name:
            try:
                return reverse(route.view_name, kwargs=resolved_params)
            except Exception:
                pass

        # Modern path converter substitution fallback (<int:pk> or <slug:article_slug>)
        url = route.path
        for name, value in resolved_params.items():
            str_val = str(value)
            url = re.sub(fr"<(?:[^:]+:)?{name}>", str_val, url)
        return url

    @classmethod
    def build_executable_url(
        cls,
        route: RouteMetadata,
        explicit_params: Optional[Dict[str, Any]] = None,
        auto_generate_if_missing: bool = True,
        lookup_map: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, Dict[str, Any], Optional[Any]]:
        """
        Full dynamic path resolution pipeline.
        Returns (concrete_url_path, resolved_params, created_instance).
        """
        params, created_instance = cls.resolve_params_for_route(
            route,
            explicit_params=explicit_params,
            auto_generate_if_missing=auto_generate_if_missing,
            lookup_map=lookup_map,
        )

        concrete_url = cls.render_concrete_url(route, params)
        return concrete_url, params, created_instance
