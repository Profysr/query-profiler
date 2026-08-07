"""
Path Converter Engine & Dynamic Parameter Resolver
==================================================
Resolves parameterized Django URL routes (such as `/books/<int:pk>/` or `/orgs/<int:org_id>/projects/<int:proj_id>/`) by identifying required path parameters, fetching or generating concrete model instances
inside safe savepoints, traversing relational trees, and constructing executable URL paths.
No synthetic dummy fallbacks (e.g. `1` or `"test-slug"`) are used, unresolved parameters are handed off to the agent/user.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Type
from django.apps import apps
from django.db import models
from django.urls import URLPattern, reverse
from django.urls.resolvers import RoutePattern
from .introspector import PathParam, RouteMetadata
from .types import PathParam, RouteMetadata
from .router import profiling_session
from .mock_generator import ModelBakeryGenerator

logger = logging.getLogger("da_profiler.converters")


class PathConverterResolver:
    """
    Modular, step-driven parameter resolution engine for Django/DRF endpoints.
    """

    @classmethod
    def resolve_converter_type(cls, converter_name: str) -> str:
        """
        Normalizes a Django converter class name to a simple type string.
        e.g. 'intconverter' -> 'int', 'slugconverter' -> 'slug', '' -> 'str'
        """
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
    def extract_from_model_instance(
        cls,
        instance: models.Model,
        param_name: str,
        lookup_map: Optional[Dict[str, str]] = None,
    ) -> Optional[Any]:
        """
        Extracts parameter value from a model instance using exact field/lookup mapping.
        No fuzzy reflection guessing, missing parameters are handed over to caller.
        """
        lookup_map = lookup_map or {}
        model_field_name = lookup_map.get(param_name, param_name)
        # If the resolved field name is "pk" or "id", it directly returns Django's built-in primary key
        if model_field_name in ("pk", "id"):
            return instance.pk

        if hasattr(instance, model_field_name):
            val = getattr(instance, model_field_name)
            return val() if callable(val) else val

        return None

    @classmethod
    def resolve_params_for_route(
        cls,
        route: RouteMetadata,
        explicit_params: Optional[Dict[str, Any]] = None,
        auto_generate_if_missing: bool = True,
        lookup_map: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, Any], Optional[Any]]:
        """
        Resolves concrete values for required path parameters of a route.
        Returns a tuple of (resolved_path_params_dict, created_mock_instance_or_none).
        Unresolved parameters are NOT given dummy synthetic fallbacks.

        Run Mock Generator
        │
        ├──► Did it create new records?
        │      ├─ YES ──► instance = new record
        │      │          created_instance = new record
        │      │
        │      └─ NO  ──► instance = model_class.objects.first()  (Existing record)
        │                 created_instance = None
        │
        ▼
        Extract path parameters from `instance`
        │
        ▼
        Return (resolved_params, created_instance)
        """
        with profiling_session():
            resolved: Dict[str, Any] = dict(explicit_params or {})

            if not route.has_path_params:
                return resolved, None

            missing_params = [p for p in route.path_params if p.name not in resolved]
            if not missing_params:
                return resolved, None

            created_instance = None

            if not (route.target_model and auto_generate_if_missing):
                return resolved, None

            # 2: Defensive check on target_model format
            if not isinstance(route.target_model, str) or route.target_model.count(".") != 1:
                logger.error(
                    f"Invalid target_model format '{route.target_model}' on route '{route.path}'. Expected 'app_label.ModelName'."
                )
                return resolved, None

            app_label, model_name = route.target_model.split(".")

            # 3: Target specific exception types
            try:
                model_class = apps.get_model(app_label, model_name)
            except (LookupError, ValueError) as err:
                logger.warning(f"Could not load model '{route.target_model}' for route '{route.path}': {err}")
                return resolved, None

            try:
                # Seed or fetch DB instance
                seed_res = ModelBakeryGenerator.ensure_capped_seeding(
                    model_class
                )
                
                raw_instances = seed_res.get("raw_instances", [])
                if raw_instances:
                    instance = raw_instances[0]
                    created_instance = instance
                else:
                    instance = model_class.objects.first()

                if instance is not None:
                    for p in missing_params:
                        val = cls.extract_from_model_instance(instance, p.name, lookup_map)
                        if val is not None:
                            resolved[p.name] = val
                        else:
                            # 4: Diagnostic logging for failed parameter extractions
                            logger.debug(
                                f"Parameter '{p.name}' could not be extracted from {model_class.__name__} instance on route {route.path}."
                            )
                else:
                    logger.warning(f"No database instances available for {model_class.__name__} on route {route.path}.")

            except DjangoDatabaseError as db_err:
                logger.error(f"Database operation failed during parameter resolution for {route.path}: {db_err}")
            except Exception as err:
                # Unexpected system/code error logged as error instead of silent warning
                logger.exception(f"Unexpected error during route parameter resolution for {route.path}: {err}")

            return resolved, created_instance

    @classmethod
    def render_concrete_url(
        cls,
        route: RouteMetadata,
        resolved_params: Dict[str, Any],
    ) -> str:
        """
        Renders a final executable URL string via Django reverse() or path substitution.
        converts /api/posts/<int:post_id>/comments/<slug:comment_slug>/ ----> /api/posts/42/comments/hello-world/
        """
        if route.view_name:
            try:
                return reverse(route.view_name, kwargs=resolved_params)
            except Exception:
                pass

        # Path converter substitution fallback (<int:pk> or <slug:article_slug>)
        url = route.path
        for name, value in resolved_params.items():
            str_val = str(value)
            # Compile the pattern and use a lambda function replacement.
            # This ensures re.sub treats str_val strictly as a literal string,
            # neutralizing issues with special characters like '\' or '$'.
            pattern = re.compile(fr"<(?:[^:]+:)?{name}>")
            url = pattern.sub(lambda m: str_val, url)

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
