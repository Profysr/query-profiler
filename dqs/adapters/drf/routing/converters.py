"""
Path Converter Engine & Dynamic Parameter Resolver (dqs/adapters/drf/converters.py)
=====================================================================================
Resolves parameterized Django URL routes by identifying required path parameters,
first searching for existing database records, mapped DRF view parameters (e.g. lookup_field / lookup_url_kwarg),
and falling back to model_bakery instance generation.

If dynamic path resolution or mock generation cannot be resolved, an exception is raised
that is captured by the runner to request user/agent manual seeding (2-3 records).
"""

# =============================================================================
# Step 01 - Imports, Logger & Configuration Setup
# =============================================================================
import inspect
import logging
import re
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import DatabaseError as DjangoDatabaseError
from django.db import models
from django.urls import URLPattern, reverse
from django.urls.exceptions import NoReverseMatch
from django.urls.resolvers import RoutePattern

from dqs.adapters.drf.mocking.generator import ModelBakeryGenerator
from dqs.adapters.drf.router import SHADOW_DB_ALIAS, profiling_session
from dqs.adapters.drf.types import PathParam, RouteMetadata, SeedDataRequiredError

logger = logging.getLogger("da_profiler.converters")


# =============================================================================
# Step 02 - Converter Type Normalization & URL Pattern Parsing
# =============================================================================
class PathConverterResolver:
    """
    Modular, step-driven parameter resolution engine for Django/DRF endpoints.
    """

    @classmethod
    def resolve_converter_type(cls, converter_name: str) -> str:
        """Step 02.1 - Normalizes converter type names (e.g., 'IntConverter' -> 'int')."""
        return converter_name or "str"

    @classmethod
    def extract_converters_from_pattern(cls, pattern: URLPattern) -> list[PathParam]:
        """Step 02.2 - Parses Django RoutePattern instances to extract path parameter names and types."""
        route_pattern = getattr(pattern, "pattern", None)
        params: list[PathParam] = []

        if isinstance(route_pattern, RoutePattern):
            for name, converter in route_pattern.converters.items():
                conv_type = cls.resolve_converter_type(type(converter).__name__.replace("Converter", "").lower())
                params.append(PathParam(name=name, converter=conv_type))

        return params

    # =========================================================================
    # Step 03 - Automated DRF View Lookup Field Inspector
    # =========================================================================
    @classmethod
    def build_auto_lookup_map(cls, view_callable: Any | None) -> dict[str, str]:
        """
        Step 03.1 - Inspects DRF ViewSets / Views to extract lookup_field and lookup_url_kwarg mappings.
        Maps URL kwarg (e.g., 'hash') -> Model Field (e.g., 'sha_256').
        """
        if not view_callable:
            return {}

        view_class = view_callable if inspect.isclass(view_callable) else getattr(view_callable, "cls", None)
        if not view_class:
            return {}

        lookup_field = getattr(view_class, "lookup_field", "pk")
        lookup_url_kwarg = getattr(view_class, "lookup_url_kwarg", None) or lookup_field

        return {lookup_url_kwarg: lookup_field}

    # =========================================================================
    # Step 04 - Model Instance Attribute & Field Extractor
    # =========================================================================
    @classmethod
    def extract_from_model_instance(
        cls,
        instance: models.Model,
        param_name: str,
        lookup_map: dict[str, str] | None = None,
    ) -> Any | None:
        """
        Step 04.1 - Extracts parameter value from a model instance using exact field or DRF lookup mapping.
        Supports:
        1. Direct model field match (e.g., books/<int:id> -> instance.id)
        2. View lookup field mapping (e.g., books/<str:hash> -> lookup_map['hash'] = 'sha_256' -> instance.sha_256)
        """
        lookup_map = lookup_map or {}
        model_field_name = lookup_map.get(param_name, param_name)

        if model_field_name in ("pk", "id"):
            return instance.pk

        if hasattr(instance, model_field_name):
            val = getattr(instance, model_field_name)
            return val() if callable(val) else val

        return None

    # =========================================================================
    # Step 05 - Dynamic Path Parameter Resolution Engine
    # =========================================================================
    @classmethod
    def resolve_params_for_route(
        cls,
        route: RouteMetadata,
        explicit_params: dict[str, Any] | None = None,
        auto_generate_if_missing: bool = True,
        lookup_map: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], Any | None]:
        """
        Step 05.1 - Resolves concrete values for required path parameters of a route.
        """
        with profiling_session():
            resolved: dict[str, Any] = dict(explicit_params or {})

            if not route.has_path_params:
                return resolved, None

            missing_params = [p for p in route.path_params if p.name not in resolved]
            if not missing_params:
                return resolved, None

            created_instance = None

            # Step 05.2 - Target Model Verification & Resolution
            if not route.target_model or not isinstance(route.target_model, str) or route.target_model.count(".") != 1:
                logger.warning(
                    f"Invalid target_model format '{route.target_model}' on route '{route.path}'."
                )
                model_class = None
            else:
                app_label, model_name = route.target_model.split(".")
                try:
                    model_class = apps.get_model(app_label, model_name)
                except (LookupError, ValueError) as err:
                    logger.warning(f"Could not load model '{route.target_model}' for route '{route.path}': {err}")
                    model_class = None

            # Step 05.3 - Database Record Search (Shadow DB with Default Fallback)
            if model_class is not None:
                # FIX: Checked settings.DATABASES instead of apps.settings.DATABASES
                db_alias = SHADOW_DB_ALIAS if SHADOW_DB_ALIAS in settings.DATABASES else "default"

                try:
                    instance = model_class.objects.using(db_alias).first()
                    # FIX: Avoid duplicate queries if db_alias is already 'default'
                    if not instance and db_alias != "default":
                        instance = model_class.objects.first()

                    # Step 05.4 - Automatic Mock Seeding Fallback
                    if instance is None and auto_generate_if_missing:
                        seed_res = ModelBakeryGenerator.ensure_capped_seeding(model_class)
                        raw_instances = seed_res.get("raw_instances", [])
                        if raw_instances:
                            instance = raw_instances[0]
                            created_instance = instance

                    # Step 05.5 - Parameter Extraction & Auto-Lookup Map Resolution
                    effective_lookup_map = cls.build_auto_lookup_map(getattr(route, "view_callable", None))
                    if hasattr(route, "lookup_map") and route.lookup_map:
                        effective_lookup_map.update(route.lookup_map)
                    if lookup_map:
                        effective_lookup_map.update(lookup_map)

                    if instance is not None:
                        for p in missing_params:
                            val = cls.extract_from_model_instance(instance, p.name, effective_lookup_map)
                            if val is not None:
                                resolved[p.name] = val
                            else:
                                logger.debug(
                                    f"Parameter '{p.name}' could not be extracted from {model_class.__name__} instance on route {route.path}."
                                )

                except DjangoDatabaseError as db_err:
                    logger.error(f"Database operation failed during parameter resolution for {route.path}: {db_err}")
                except SeedDataRequiredError:
                    raise
                except Exception:
                    logger.exception(f"Unexpected error during route parameter resolution for {route.path}")

            # Step 05.6 - Validation & SeedDataRequiredError Handoff
            still_missing = [p.name for p in route.path_params if p.name not in resolved]
            if still_missing:
                model_info = route.target_model or "Unknown Model"
                raise SeedDataRequiredError(
                    f"Could not resolve dynamic path parameter(s) '{', '.join(still_missing)}' for route '{route.path}'. "
                    f"Please provide 2 to 3 valid database records for model '{model_info}' manually."
                )

            return resolved, created_instance

    # =========================================================================
    # Step 06 - Concrete URL Rendering & String Interpolation
    # =========================================================================
    @classmethod
    def render_concrete_url(
        cls,
        route: RouteMetadata,
        resolved_params: dict[str, Any],
    ) -> str:
        """
        Step 06.1 - Renders executable URL using reverse() or regex pattern substitution fallback.
        """
        if route.view_name:
            try:
                return reverse(route.view_name, kwargs=resolved_params)
            except NoReverseMatch:
                logger.debug("Failed to reverse route %s with params %s", route.view_name, resolved_params)

        url = route.path
        for name, value in resolved_params.items():
            str_val = str(value)
            pattern = re.compile(fr"<(?:[^:]+:)?{name}>")
            url = pattern.sub(lambda m, val=str_val: val, url)

        return url

    # =========================================================================
    # Step 07 - High-Level Executable URL Builder Entry Point
    # =========================================================================
    @classmethod
    def build_executable_url(
        cls,
        route: RouteMetadata,
        explicit_params: dict[str, Any] | None = None,
        auto_generate_if_missing: bool = True,
        lookup_map: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any], Any | None]:
        """
        Step 07.1 - Primary entry point: Resolves parameter dictionary and renders final concrete URL string.
        """
        params, created_instance = cls.resolve_params_for_route(
            route,
            explicit_params=explicit_params,
            auto_generate_if_missing=auto_generate_if_missing,
            lookup_map=lookup_map,
        )

        concrete_url = cls.render_concrete_url(route, params)
        return concrete_url, params, created_instance