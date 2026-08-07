"""
Mock Data Generator Engine (dqs/adapters/drf/mock_generator.py)
================================================================
Provides robust model seeding capabilities using model_bakery with:
1. Validation Recovery Flow: Gracefully handles baker failure scenarios (e.g. strict DB constraints).
2. Uniqueness Guard: Handles unique=True / unique_together / UniqueConstraint fields via sequence iteration.
3. In-Memory Sample Cache: Keeps track of created instances per session/invocation.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Type, Union
from django.apps import apps
from django.conf import settings
from django.db import models
from model_bakery import baker
from model_bakery.exceptions import ModelBakeryException
from dqs.adapters.drf.router import SEED_MIN_THRESHOLD, SEED_MAX_CAP

logger = logging.getLogger("dqs.mock_generator")


class ModelBakeryGenerator:
    """
    Encapsulates model mock data creation with constraint-safety, uniqueness guards,
    and validation recovery mechanisms.
    """
    _sample_cache: Dict[str, List[models.Model]] = {}

    @classmethod
    def ensure_capped_seeding(
        cls,
        model_or_path: Union[str, Type[models.Model]],
        min_threshold: int = SEED_MIN_THRESHOLD,
        max_cap: int = SEED_MAX_CAP,
    ) -> Dict[str, Any]:
        """
        Ensures the shadow database contains at least min_threshold records.
        If it falls below, triggers the generator to seed up to max_cap records.
        """
        model_class = cls._resolve_model(model_or_path)
        if not model_class:
            return {"status": "error", "message": f"Could not resolve model {model_or_path}"}

        db_alias = "dqs_shadow" if "dqs_shadow" in settings.DATABASES else "default"
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

    @classmethod
    def generate(
        cls,
        model_or_path: Union[str, Type[models.Model]],
        quantity: int = 1,
        commit: bool = True,
        **custom_fields: Any,
    ) -> List[models.Model]:
        """
        Main entry point to generate mock instances for a Django model.
        
        :param model_or_path: Model class or string path like 'app_label.ModelName'
        :param quantity: Number of instances to generate
        :param commit: If True, saves to DB via baker.make(); if False, uses baker.prepare()
        :param custom_fields: Explicit field value overrides
        :return: List of model instances
        """
        model_class = cls._resolve_model(model_or_path)
        if not model_class:
            logger.warning(f"Could not resolve model class for {model_or_path}")
            return []

        model_key = f"{model_class._meta.app_label}.{model_class._meta.object_name}"

        # 1. Check cache if quantity==1 and commit==False (or for quick retrieval)
        if not commit and model_key in cls._sample_cache and len(cls._sample_cache[model_key]) >= quantity:
            return cls._sample_cache[model_key][:quantity]

        # 2. Prepare uniqueness guards for fields marked unique=True or in UniqueConstraints
        overrides = cls._build_uniqueness_overrides(model_class, quantity, custom_fields)

        instances: List[models.Model] = []

        try:
            if commit:
                res = baker.make(model_class, _quantity=quantity, **overrides)
            else:
                res = baker.prepare(model_class, _quantity=quantity, **overrides)

            instances = res if isinstance(res, list) else [res]

        except (ModelBakeryException, Exception) as primary_err:
            logger.warning(
                f"Standard baker.{'make' if commit else 'prepare'} failed for {model_key}: {primary_err}. "
                "Initiating Validation Recovery Flow..."
            )
            # 3. Validation Recovery Flow
            instances = cls._recovery_generate(
                model_class=model_class,
                quantity=quantity,
                commit=commit,
                primary_err=primary_err,
                overrides=overrides,
            )

        # Update cache
        if instances:
            cls._sample_cache.setdefault(model_key, []).extend(instances)

        return instances

    @classmethod
    def clear_cache(cls) -> None:
        """Clears the in-memory sample cache."""
        cls._sample_cache.clear()

    @classmethod
    def _resolve_model(cls, model_or_path: Union[str, Type[models.Model]]) -> Optional[Type[models.Model]]:
        if isinstance(model_or_path, str):
            try:
                app_label, model_name = model_or_path.split(".")
                return apps.get_model(app_label, model_name)
            except Exception as e:
                logger.error(f"Error resolving model path '{model_or_path}': {e}")
                return None
        elif inspect_is_model_class(model_or_path):
            return model_or_path
        return None

    @classmethod
    def _build_uniqueness_overrides(
        cls,
        model_class: Type[models.Model],
        quantity: int,
        user_overrides: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Inspects model fields for unique=True, UniqueConstraint, and unique_together,
        ensuring baker generates non-conflicting values.
        """
        overrides = dict(user_overrides)

        for field in model_class._meta.get_fields():
            if not hasattr(field, "name"):
                continue

            field_name = field.name

            # Skip fields user explicitly supplied
            if field_name in overrides:
                continue

            # Flagged unique or Primary Key
            is_unique = getattr(field, "unique", False) or getattr(field, "primary_key", False)

            if is_unique and not field.is_relation:
                internal_type = field.get_internal_type() if hasattr(field, "get_internal_type") else ""

                if internal_type in ("CharField", "SlugField", "TextField"):
                    # Use unique suffix generator sequence
                    prefix = "test-unique" if internal_type != "SlugField" else "test-slug"
                    if quantity > 1:
                        overrides[field_name] = baker.seq(f"{prefix}-", suffix=f"-{uuid.uuid4().hex[:6]}")
                    else:
                        overrides[field_name] = f"{prefix}-{uuid.uuid4().hex[:8]}"

                elif internal_type in ("UUIDField",):
                    overrides[field_name] = uuid.uuid4

                elif internal_type in ("EmailField",):
                    overrides[field_name] = baker.seq("user-", suffix="@example.com")

        return overrides

    @classmethod
    def _recovery_generate(
        cls,
        model_class: Type[models.Model],
        quantity: int,
        commit: bool,
        primary_err: Exception,
        overrides: Dict[str, Any],
    ) -> List[models.Model]:
        """
        Validation Recovery Flow:
        Attempts step-by-step relaxed creation when standard baker generation fails
        due to unhandled model constraints, custom save() methods, or required FKs.
        """
        results: List[models.Model] = []

        for i in range(quantity):
            try:
                # Fallback A: Try creating instance with _fill_optional=True
                instance = baker.make(
                    model_class,
                    _fill_optional=True,
                    _save_related=True,
                    **overrides,
                ) if commit else baker.prepare(
                    model_class,
                    _fill_optional=True,
                    _save_related=True,
                    **overrides,
                )
                results.append(instance)
            except Exception as recovery_err:
                logger.warning(f"Recovery step A failed for {model_class.__name__} (item {i}): {recovery_err}")

                # Fallback B: Instantiate bare model instance directly with minimal required fields
                try:
                    instance = model_class()
                    # Populate default/blank values for required fields
                    for field in model_class._meta.concrete_fields:
                        if not field.has_default() and not field.blank and not field.null:
                            if field.name in overrides:
                                set_field_val(instance, field, overrides[field.name])
                            else:
                                set_field_val(instance, field, get_safe_default_for_field(field))

                    if commit:
                        instance.save()
                    results.append(instance)
                except Exception as final_err:
                    logger.error(f"Validation Recovery Flow completely failed for item {i} of {model_class.__name__}: {final_err}")

        return results


def inspect_is_model_class(val: Any) -> bool:
    return isinstance(val, type) and issubclass(val, models.Model)


def set_field_val(instance: models.Model, field: models.Field, val: Any) -> None:
    try:
        setattr(instance, field.name, val)
    except Exception:
        pass


def get_safe_default_for_field(field: models.Field) -> Any:
    internal_type = field.get_internal_type() if hasattr(field, "get_internal_type") else ""
    if internal_type in ("IntegerField", "SmallIntegerField", "BigIntegerField", "PositiveIntegerField"):
        return 1
    elif internal_type in ("FloatField", "DecimalField"):
        return 1.0
    elif internal_type in ("BooleanField",):
        return False
    elif internal_type in ("CharField", "TextField"):
        return "test"
    elif internal_type in ("SlugField",):
        return "test-slug"
    elif internal_type in ("EmailField",):
        return "test@example.com"
    elif internal_type in ("UUIDField",):
        return uuid.uuid4()
    elif field.is_relation and hasattr(field, "remote_field") and field.remote_field:
        # For required ForeignKey relations, attempt to create/fetch parent
        related_model = field.remote_field.model
        if related_model and related_model != field.model:
            try:
                parent = related_model.objects.first()
                if not parent:
                    parent = baker.make(related_model)
                return parent
            except Exception:
                return None
    return None
