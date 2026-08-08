"""
Schema-level static checks — cross-references actual Django model metadata
(indexes, PK field type) against how a target's code queries that model.
Unlike static_advisor.py, this requires the Django app registry to be loaded
(model classes must exist), but still requires NO live DB connection and NO
code execution — models are just Python classes with metadata attached.
"""
from typing import Any

from django.apps import apps

# PK field types considered "auto-increment integer" style — the case the
# roadmap wants flagged in favor of UUID-based PKs for write-heavy/distributed
# workloads (sortable, index-friendly UUIDv7 specifically, unlike UUIDv4).
AUTO_INCREMENT_PK_TYPES = {"AutoField", "BigAutoField", "SmallAutoField"}


def check_pk_strategy(model_path: str | None) -> list[dict[str, Any]]:
    """Flags models using auto-increment integer PKs, suggesting UUIDv7."""
    if not model_path:
        return []
    try:
        app_label, model_name = model_path.split(".")
        model = apps.get_model(app_label, model_name)
    except Exception:
        return []

    pk_field = model._meta.pk
    pk_type = pk_field.get_internal_type()

    if pk_type in AUTO_INCREMENT_PK_TYPES:
        return [{
            "type": "PK_STRATEGY_ADVICE",
            "message": (
                f"Model '{model_path}' uses an auto-increment integer PK ('{pk_type}'). "
                f"For write-heavy or distributed workloads, consider a UUIDv7 PK instead — "
                f"it's sortable (unlike UUIDv4) and avoids sequential-ID contention/enumeration issues."
            ),
            "severity": "low",
            "model": model_path,
        }]
    return []


def check_missing_indexes(model_path: str | None, queried_fields: list[str]) -> list[dict[str, Any]]:
    """
    Cross-references fields used in .filter()/.exclude()/.order_by() calls
    against the model's actual indexed fields (db_index=True, unique=True,
    or listed in Meta.indexes). Flags fields that are queried but not indexed.
    """
    if not model_path or not queried_fields:
        return []
    try:
        app_label, model_name = model_path.split(".")
        model = apps.get_model(app_label, model_name)
    except Exception:
        return []

    indexed_field_names = set()

    # 1. Fields with db_index=True or unique=True (implicitly indexed)
    for field in model._meta.get_fields():
        if getattr(field, "db_index", False) or getattr(field, "unique", False):
            indexed_field_names.add(field.name)

    # 2. Fields covered by explicit Meta.indexes entries
    for index in getattr(model._meta, "indexes", []):
        indexed_field_names.update(index.fields)

    # Always-indexed by default: the PK itself
    indexed_field_names.add(model._meta.pk.name)

    findings = []
    for field_name in set(queried_fields):
        clean_name = field_name.lstrip("-").split("__")[0]  # strip order_by "-" and lookup suffixes like __gte
        if clean_name and clean_name not in indexed_field_names:
            findings.append({
                "type": "MISSING_INDEX",
                "message": (
                    f"Field '{clean_name}' on model '{model_path}' is queried via filter/exclude/order_by "
                    f"but has no index (db_index, unique, or Meta.indexes entry). Consider adding one if "
                    f"this field is queried frequently or the table is large."
                ),
                "severity": "medium",
                "model": model_path,
                "field": clean_name,
            })
    return findings