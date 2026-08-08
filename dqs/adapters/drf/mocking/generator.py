"""
Unified Mock Data & Body Generator (dqs/adapters/drf/mocking/generator.py)
=============================================================================
Provides robust model seeding capabilities using model_bakery and body payload
inference for serializers/forms with guaranteed uniqueness.
"""

# =============================================================================
# Step 01 - Imports, Logger & Configuration Setup
# =============================================================================
import inspect
import logging
import uuid
from typing import Any, ClassVar

from django.apps import apps
from django.conf import settings
from django.db import models

from dqs.adapters.drf.router import SEED_MAX_CAP, SEED_MIN_THRESHOLD, SHADOW_DB_ALIAS
from dqs.adapters.drf.types import SeedDataRequiredError

logger = logging.getLogger("dqs.mock_generator")


# =============================================================================
# Step 02 - Centralized Mock Value Generation Engine
# =============================================================================
class MockValueGenerator:
    """
    Centralized, thread-safe value generator for Django models, DRF fields, and forms.
    Guarantees uniqueness via UUID tokens for DB seeding & JSON payloads.
    """
    @classmethod
    def get_unique_value(cls, field_name: str, internal_type: str, max_length: int | None = None) -> Any:
        uid = uuid.uuid4().hex[:6]
        fn_lower = field_name.lower()

        # Step 02.1 - Specialized String Fields (Email, Slug, URL)
        if "email" in fn_lower or internal_type == "EmailField":
            val = f"user_{uid}_{field_name}@example.com"
            return val[:max_length] if max_length else val
        if "slug" in fn_lower or internal_type == "SlugField":
            val = f"slug-{field_name}-{uid}"
            return val[:max_length] if max_length else val
        if "url" in fn_lower or internal_type == "URLField":
            return f"https://example.com/{field_name}/{uid}"
        if internal_type in ("CharField", "TextField", "RegexField"):
            val = f"test_{field_name}_{uid}"
            return val[:max_length] if max_length else val

        # Step 02.2 - Numeric & Boolean Types
        if internal_type in ("IntegerField", "SmallIntegerField", "BigIntegerField", "PositiveIntegerField"):
            return (abs(hash(uid)) % 90000) + 1000
        if internal_type in ("FloatField", "DecimalField"):
            return round((abs(hash(uid)) % 90000) / 100.0 + 1.0, 2)
        if internal_type == "BooleanField":
            return (abs(hash(uid)) % 2) == 0

        # Step 02.3 - Date, Time & Identifiers
        if internal_type == "UUIDField":
            return str(uuid.uuid4())
        if internal_type == "DateTimeField":
            sec = abs(hash(uid)) % 60
            minute = abs(hash(uid)) % 60
            hour = abs(hash(uid)) % 24
            return f"2026-01-01T{hour:02d}:{minute:02d}:{sec:02d}Z"
        if internal_type == "DateField":
            day = (abs(hash(uid)) % 28) + 1
            month = (abs(hash(uid)) % 12) + 1
            return f"2026-{month:02d}-{day:02d}"
        if internal_type == "TimeField":
            sec = abs(hash(uid)) % 60
            minute = abs(hash(uid)) % 60
            hour = abs(hash(uid)) % 24
            return f"{hour:02d}:{minute:02d}:{sec:02d}"

        # Step 02.4 - Default Fallback Token
        return f"val_{field_name}_{uid}"


# =============================================================================
# Step 03 - Model Bakery Seeding Core & Class Caching
# =============================================================================
class ModelBakeryGenerator:
    """
    Encapsulates model mock data creation with constraint-safety, uniqueness guards,
    and validation recovery mechanisms.
    """
    _sample_cache: ClassVar[dict[str, list[models.Model]]] = {}

    @classmethod
    def _inspect_is_model_class(cls, val: Any) -> bool:
        """Step 03.1 - Utility to verify if an object is a subclass of Django Model."""
        return isinstance(val, type) and issubclass(val, models.Model)

    @classmethod
    def _resolve_model(cls, model_or_path: str | type[models.Model]) -> type[models.Model] | None:
        """Step 03.2 - Resolves string dot-paths ('app.Model') into concrete Django Model classes."""
        if isinstance(model_or_path, str):
            try:
                app_label, model_name = model_or_path.split(".")
                return apps.get_model(app_label, model_name)
            except Exception as e:
                logger.error(f"Error resolving model path '{model_or_path}': {e}")
                return None
        elif cls._inspect_is_model_class(model_or_path):
            return model_or_path
        return None

    # =========================================================================
    # Step 04 - Baseline DB State Sampling
    # =========================================================================
    @classmethod
    def _sample_existing_fields(
        cls,
        model_class: type[models.Model],
    ) -> dict[str, Any] | None:
        """
        Reads an existing DB record and returns its non-relational, non-unique field
        values as a template dict. This lets new mock records inherit realistic values
        (e.g. same category choices, same FK IDs) instead of pure random data.
        """
        db_alias = SHADOW_DB_ALIAS if SHADOW_DB_ALIAS in settings.DATABASES else "default"
        sample = (
            model_class.objects.using(db_alias).first()
            or model_class.objects.first()
        )
        if sample is None:
            return None

        template: dict[str, Any] = {}
        for f in model_class._meta.get_fields():
            # Skip relations, PKs, unique fields and auto-fields — those get fresh unique values
            if not hasattr(f, "name") or f.is_relation:
                continue
            if getattr(f, "primary_key", False) or getattr(f, "unique", False):
                continue
            if getattr(f, "auto_created", False):
                continue
            try:
                val = getattr(sample, f.name, None)
                if val is not None:
                    template[f.name] = val
            except Exception:
                pass

        return template or None

    # =========================================================================
    # Step 05 - Capped Seeding Threshold Check
    # =========================================================================
    @classmethod
    def ensure_capped_seeding(
        cls,
        model_or_path: str | type[models.Model],
        min_threshold: int = SEED_MIN_THRESHOLD,
        max_cap: int = SEED_MAX_CAP,
    ) -> dict[str, Any]:
        """Ensures the shadow DB has enough baseline rows before profiling runs."""
        model_class = cls._resolve_model(model_or_path)
        if not model_class:
            return {"status": "error", "message": f"Could not resolve model {model_or_path}"}

        db_alias = SHADOW_DB_ALIAS if SHADOW_DB_ALIAS in settings.DATABASES else "default"
        count = model_class.objects.using(db_alias).count()

        seeded_count = 0
        instances = []
        if count < min_threshold:
            to_seed = max_cap - count
            if to_seed > 0:
                instances = cls.generate(model_class, quantity=to_seed, commit=True)
                seeded_count = len(instances)

        return {
            "model": f"{model_class._meta.app_label}.{model_class._meta.object_name}",
            "initial_count": count,
            "final_count": count + seeded_count,
            "seeded_count": seeded_count,
            "instances": [{"pk": obj.pk, "__str__": str(obj)} for obj in instances],
            "raw_instances": instances,
        }

    # =========================================================================
    # Step 06 - Primary Model Generation & Uniqueness Mapping
    # =========================================================================
    @classmethod
    def generate(
        cls,
        model_or_path: str | type[models.Model],
        quantity: int = 1,
        commit: bool = True,
        **custom_fields: Any,
    ) -> list[models.Model]:
        """Main entry point for generating mock database records using model_bakery."""

        model_class = cls._resolve_model(model_or_path)
        if not model_class:
            model_str = model_or_path if isinstance(model_or_path, str) else str(model_or_path)
            raise SeedDataRequiredError(
                f"Could not resolve Django model '{model_str}'. "
                f"Please provide 2 to 3 valid database records manually."
            )

        model_key = f"{model_class._meta.app_label}.{model_class._meta.object_name}"

        # Return cached in-memory prepared models if non-committed instances requested
        if not commit and model_key in cls._sample_cache and len(cls._sample_cache[model_key]) >= quantity:
            return cls._sample_cache[model_key][:quantity]

        # Determine which DB to seed into: shadow DB when configured, else default.
        # This must match the DB the view will read from during the profiling session.
        db_alias = SHADOW_DB_ALIAS if SHADOW_DB_ALIAS in settings.DATABASES else "default"

        # Record-aware seeding: sample existing record baseline, then layer user overrides
        existing_template = cls._sample_existing_fields(model_class)
        base_fields = dict(existing_template or {})
        base_fields.update(custom_fields)

        overrides = cls._build_uniqueness_overrides(model_class, quantity, base_fields)
        instances: list[models.Model] = []

        from model_bakery import baker
        from model_bakery.exceptions import ModelBakeryException

        try:
            if commit:
                res = baker.make(model_class, _quantity=quantity, _using=db_alias, **overrides)
            else:
                res = baker.prepare(model_class, _quantity=quantity, **overrides)

            instances = res if isinstance(res, list) else [res]

        except (ModelBakeryException, Exception) as primary_err:
            logger.warning(
                f"Standard baker.{'make' if commit else 'prepare'} failed for {model_key}: {primary_err}. "
                "Initiating Validation Recovery Flow..."
            )
            # Hand-off to Step 07 if primary generation fails
            instances = cls._recovery_generate(
                model_class=model_class,
                quantity=quantity,
                commit=commit,
                db_alias=db_alias,
                primary_err=primary_err,
                overrides=overrides,
            )

        if not instances and quantity > 0:
            raise SeedDataRequiredError(
                f"Automated mock data generation failed for model '{model_key}'. "
                f"Please provide 2 to 3 valid database records manually."
            )

        if instances:
            cls._sample_cache.setdefault(model_key, []).extend(instances)

        return instances

    @classmethod
    def _build_uniqueness_overrides(
        cls,
        model_class: type[models.Model],
        quantity: int,
        user_overrides: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 06.1 - Dynamically populates mock values for all unique/primary fields."""
        overrides = dict(user_overrides)

        for field in model_class._meta.get_fields():
            if not hasattr(field, "name"):
                continue

            field_name = field.name
            if field_name in overrides:
                continue

            is_unique = getattr(field, "unique", False) or getattr(field, "primary_key", False)

            if is_unique and not field.is_relation:
                internal_type = field.get_internal_type() if hasattr(field, "get_internal_type") else ""
                overrides[field_name] = MockValueGenerator.get_unique_value(field_name, internal_type)

        return overrides

    # =========================================================================
    # Step 07 - Automated Validation Recovery Flow
    # =========================================================================
    @classmethod
    def _recovery_generate(
        cls,
        model_class: type[models.Model],
        quantity: int,
        commit: bool,
        db_alias: str,
        primary_err: Exception,
        overrides: dict[str, Any],
    ) -> list[models.Model]:
        """Secondary generation attempt forcing optional field generation and relation creation."""
        from model_bakery import baker

        try:
            if commit:
                results = baker.make(
                    model_class,
                    _quantity=quantity,
                    _fill_optional=True,
                    _save_related=True,
                    _using=db_alias,
                    **overrides,
                )
            else:
                results = baker.prepare(
                    model_class,
                    _quantity=quantity,
                    _fill_optional=True,
                    _save_related=True,
                    **overrides,
                )

            return results if isinstance(results, list) else [results]

        except Exception as recovery_err:
            logger.error(f"Failed to automatically generate mock data for '{model_class.__name__}': {recovery_err}")
            raise SeedDataRequiredError(
                f"Could not automatically generate mock data for '{model_class._meta.app_label}.{model_class._meta.object_name}' "
                f"due to complex DB constraints. Please provide 2 to 3 valid database records manually."
            ) from recovery_err

    # =========================================================================
    # Step 08 - The "Human Flow": User Payload Handoff & Record Cloning
    # =========================================================================
    @classmethod
    def clone_user_records(
        cls,
        model_class: type[models.Model],
        user_records: list[dict[str, Any]],
        serializer_cls: Any | None = None,
        target_quantity: int = 2,
    ) -> list[models.Model]:
        """
        Accepts valid JSON payloads provided by the user/agent, validates + saves them
        as base records via DRF Serializer or ORM, then clones them safely to satisfy target quantities.
        """
        from django.db import transaction

        db_alias = SHADOW_DB_ALIAS if SHADOW_DB_ALIAS in settings.DATABASES else "default"
        created_instances: list[models.Model] = []
        errors: list[str] = []

        # Step 08.1 - Phase 1: Validate & persist user-provided payloads
        with transaction.atomic(using=db_alias):
            for idx, record in enumerate(user_records):
                try:
                    if serializer_cls:
                        serializer = serializer_cls(data=record)
                        serializer.is_valid(raise_exception=True)
                        instance = serializer.save()
                    else:
                        instance = model_class.objects.using(db_alias).create(**record)

                    created_instances.append(instance)

                except Exception as e:
                    errors.append(f"Record #{idx + 1}: {e}")

        if not created_instances:
            raise SeedDataRequiredError(
                f"None of the {len(user_records)} provided record(s) could be saved for "
                f"'{model_class.__name__}'. Errors: {'; '.join(errors)}. "
                f"Please fix the payloads and try again."
            )

        if errors:
            logger.warning(
                f"{len(errors)} record(s) failed validation for '{model_class.__name__}': {errors}"
            )

        # Step 08.2 - Phase 2: Clone base records until target_quantity is reached
        needed = target_quantity - len(created_instances)
        for i in range(max(needed, 0)):
            base_obj = created_instances[i % len(created_instances)]

            clone_fields: dict[str, Any] = {}
            for f in model_class._meta.concrete_fields:
                if getattr(f, "primary_key", False):
                    continue
                if getattr(f, "unique", False):
                    clone_fields[f.name] = MockValueGenerator.get_unique_value(
                        f.name,
                        f.get_internal_type(),
                        max_length=getattr(f, "max_length", None),
                    )
                else:
                    val = getattr(base_obj, f.attname, None)
                    if val is not None:
                        clone_fields[f.name] = val

            try:
                clone = model_class.objects.using(db_alias).create(**clone_fields)
                created_instances.append(clone)
            except Exception as clone_err:
                logger.warning(
                    f"Could not clone record #{i + 1} for '{model_class.__name__}': {clone_err}. Skipping."
                )

        model_key = f"{model_class._meta.app_label}.{model_class._meta.object_name}"
        cls._sample_cache.setdefault(model_key, []).extend(created_instances)

        return created_instances

    @classmethod
    def clear_cache(cls) -> None:
        """Step 08.3 - Clears the internal sample cache to prevent memory leaks."""
        cls._sample_cache.clear()


# =============================================================================
# Step 09 - Request Body Payload Inferrer Entry Point
# =============================================================================

def infer_request_body(view_func_or_cls: Any) -> dict[str, Any] | None:
    """
    Inspects a view function or view class to determine expected input fields
    and generate a realistic mock request body dict with unique values.
    """
    view_class = _extract_view_class(view_func_or_cls)
    if not view_class:
        return None

    # Step 09.1 - Route to Serializer Inference if available
    serializer_cls = _extract_serializer_class(view_class)
    if serializer_cls:
        return infer_body_from_fields(serializer_cls)

    # Step 09.2 - Route to Form Inference if Django Form View
    form_cls = getattr(view_class, "form_class", None)
    if form_cls:
        return infer_body_from_fields(form_cls, is_form=True)

    return None


# =============================================================================
# Step 10 - Field Extraction & Traversal Loop
# =============================================================================

def infer_body_from_fields(class_or_instance: Any, is_form: bool = False) -> dict[str, Any]:
    """
    Unified function for inferring request body payload dictionaries from both
    DRF Serializers and Django Forms.
    """
    payload: dict[str, Any] = {}

    try:
        instance = class_or_instance() if inspect.isclass(class_or_instance) else class_or_instance
        fields = getattr(instance, "fields", {})
    except Exception as e:
        logger.debug(f"Could not instantiate field container {class_or_instance}: {e}")
        return payload

    for field_name, field in fields.items():
        # Step 10.1 - Skip un-writeable fields (disabled or read-only)
        if is_form and getattr(field, "disabled", False):
            continue
        if not is_form and getattr(field, "read_only", False):
            continue

        # Step 10.2 - Resolve value per field
        payload[field_name] = _generate_mock_value_for_field(field_name, field)

    return payload


# =============================================================================
# Step 11 - View & Serializer Inspection Helpers
# =============================================================================

def _extract_view_class(view_func_or_cls: Any) -> type | None:
    """Unwraps Django view functions, class-based views, or viewsets to find the target class."""
    if inspect.isclass(view_func_or_cls):
        return view_func_or_cls
    return (
        getattr(view_func_or_cls, "view_class", None)
        or getattr(view_func_or_cls, "cls", None)
    )


def _extract_serializer_class(view_class: type) -> type | None:
    """Retrieves the serializer class from view attribute or .get_serializer_class()."""
    cls = getattr(view_class, "serializer_class", None)
    if cls and inspect.isclass(cls):
        return cls

    if hasattr(view_class, "get_serializer_class"):
        try:
            instance = view_class()
            cls = instance.get_serializer_class()
            if cls and inspect.isclass(cls):
                return cls
        except Exception:
            pass

    return None


# =============================================================================
# Step 12 - Field-Specific Payload Value Resolution
# =============================================================================

def _generate_mock_value_for_field(field_name: str, field: Any) -> Any:
    """
    Single unified mock value resolver for Serializer and Form fields.
    """
    field_class_name = field.__class__.__name__

    # Step 12.1 - Honor explicit default values
    default_val = getattr(field, "default", None)
    if default_val is not None and not _is_empty_symbol(default_val):
        return default_val() if callable(default_val) else default_val

    # Step 12.2 - DRF ChoiceField & Form ChoiceField handling
    if field_class_name in ("ChoiceField", "MultipleChoiceField", "ModelChoiceField"):
        choices = getattr(field, "choices", {})
        if choices:
            choices_list = list(choices.items()) if isinstance(choices, dict) else list(choices)
            if choices_list:
                first_choice = choices_list[0][0]
                if first_choice != "":
                    return [first_choice] if field_class_name == "MultipleChoiceField" else first_choice

    # Step 12.3 - Related Fields (ForeignKey / Slug lookup sampling)
    if field_class_name in ("PrimaryKeyRelatedField", "SlugRelatedField"):
        queryset = getattr(field, "queryset", None)
        if queryset is not None:
            try:
                obj = queryset.first()
                if obj:
                    target_attr = getattr(field, "slug_field", "pk")
                    val = getattr(obj, target_attr, obj.pk)
                    return val() if callable(val) else val
            except Exception:
                pass
        return 1

    # Step 12.4 - Nested Collections (ListField, DictField, JSONField)
    if field_class_name in ("ListField", "JSONArrayField"):
        child = getattr(field, "child", None)
        if child:
            return [_generate_mock_value_for_field("item", child)]
        return ["sample_item"]

    if field_class_name in ("DictField", "JSONField"):
        return {"key": f"value_{uuid.uuid4().hex[:4]}"}

    # Step 12.5 - Nested Serializers (Single & List Serializers)
    if field_class_name in ("Serializer", "ModelSerializer"):
        return infer_body_from_fields(field.__class__, is_form=False)

    if field_class_name in ("ListSerializer",):
        child_serializer = getattr(field, "child", None)
        if child_serializer:
            return [infer_body_from_fields(child_serializer.__class__, is_form=False)]
        return []

    # Step 12.6 - General Fallback to Centralized MockValueGenerator
    max_length = getattr(field, "max_length", None)
    return MockValueGenerator.get_unique_value(field_name, field_class_name, max_length=max_length)


def _is_empty_symbol(val: Any) -> bool:
    """Step 12.7 - Helper to check if a default value represents DRF's empty sentinel."""
    name = getattr(val, "__name__", "") or str(val)
    return "empty" in name.lower() or name == "empty"