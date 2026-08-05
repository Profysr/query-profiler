"""
Request Body Inferrer (dqs/adapters/drf/body_inferrer.py)
=========================================================
Inspects DRF view classes, serializer classes, or Django forms to infer
valid mock request body payloads for write HTTP methods (POST, PUT, PATCH).
"""

import inspect
import logging
from typing import Any, Dict, Optional, Type

logger = logging.getLogger("dqs.body_inferrer")


def infer_request_body(view_func_or_cls: Any) -> Optional[Dict[str, Any]]:
    """
    Inspects a view function or view class to determine expected input fields
    and generate a realistic mock request body dict.

    :param view_func_or_cls: DRF ViewSet/APIView class, as_view() wrapper, or FBV
    :return: Generated dictionary of mock field data, or None if unresolvable
    """
    view_class = _extract_view_class(view_func_or_cls)
    if not view_class:
        return None

    serializer_cls = _extract_serializer_class(view_class)
    if serializer_cls:
        return infer_body_from_serializer(serializer_cls)

    form_cls = getattr(view_class, "form_class", None)
    if form_cls:
        return infer_body_from_form(form_cls)

    return None


def infer_body_from_serializer(serializer_cls: Type) -> Dict[str, Any]:
    """
    Instantiates a DRF Serializer class and inspects its fields to produce
    mock payload data matching each field's expected type and validators.
    """
    payload: Dict[str, Any] = {}

    try:
        serializer_instance = serializer_cls()
        fields = getattr(serializer_instance, "fields", {})
    except Exception as e:
        logger.debug(f"Could not instantiate serializer {serializer_cls}: {e}")
        return payload

    for field_name, field in fields.items():
        if field.read_only:
            continue

        payload[field_name] = _generate_mock_value_for_serializer_field(field_name, field)

    return payload


def infer_body_from_form(form_cls: Type) -> Dict[str, Any]:
    """
    Instantiates a Django Form class and inspects its fields to produce mock payload data.
    """
    payload: Dict[str, Any] = {}

    try:
        form_instance = form_cls()
        fields = getattr(form_instance, "fields", {})
    except Exception as e:
        logger.debug(f"Could not instantiate form {form_cls}: {e}")
        return payload

    for field_name, field in fields.items():
        if getattr(field, "disabled", False):
            continue

        payload[field_name] = _generate_mock_value_for_form_field(field_name, field)

    return payload


def _extract_view_class(view_func_or_cls: Any) -> Optional[Type]:
    if inspect.isclass(view_func_or_cls):
        return view_func_or_cls
    return (
        getattr(view_func_or_cls, "view_class", None)
        or getattr(view_func_or_cls, "cls", None)
    )


def _extract_serializer_class(view_class: Type) -> Optional[Type]:
    # 1. Direct serializer_class attribute
    cls = getattr(view_class, "serializer_class", None)
    if cls and inspect.isclass(cls):
        return cls

    # 2. Dynamic get_serializer_class()
    if hasattr(view_class, "get_serializer_class"):
        try:
            instance = view_class()
            cls = instance.get_serializer_class()
            if cls and inspect.isclass(cls):
                return cls
        except Exception:
            pass

    return None


def _generate_mock_value_for_serializer_field(field_name: str, field: Any) -> Any:
    field_class_name = field.__class__.__name__

    # Honor default value if explicitly set
    if field.default is not None and not _is_empty_symbol(field.default):
        default_val = field.default
        return default_val() if callable(default_val) else default_val

    # Map by field class type name
    if field_class_name in ("CharField", "RegexField"):
        if "email" in field_name.lower():
            return f"test_{field_name}@example.com"
        if "slug" in field_name.lower():
            return f"test-{field_name}"
        if "url" in field_name.lower():
            return "https://example.com"
        max_length = getattr(field, "max_length", None)
        val = f"test_{field_name}"
        return val[:max_length] if max_length else val

    elif field_class_name == "EmailField":
        return f"test_{field_name}@example.com"

    elif field_class_name == "SlugField":
        return f"test-{field_name}"

    elif field_class_name == "URLField":
        return "https://example.com"

    elif field_class_name == "UUIDField":
        return "123e4567-e89b-12d3-a456-426614174000"

    elif field_class_name in ("IntegerField", "IntegerField"):
        min_val = getattr(field, "min_value", None)
        return max(1, min_val) if min_val is not None else 1

    elif field_class_name in ("FloatField", "DecimalField"):
        return 1.0

    elif field_class_name == "BooleanField":
        return True

    elif field_class_name == "DateTimeField":
        return "2026-01-01T00:00:00Z"

    elif field_class_name == "DateField":
        return "2026-01-01"

    elif field_class_name == "TimeField":
        return "12:00:00"

    elif field_class_name in ("ChoiceField", "MultipleChoiceField"):
        choices = getattr(field, "choices", {})
        if choices:
            first_choice = next(iter(choices.keys()))
            return [first_choice] if field_class_name == "MultipleChoiceField" else first_choice
        return "choice_1"

    elif field_class_name in ("PrimaryKeyRelatedField", "SlugRelatedField"):
        # Look for existing model record or mock PK
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

    elif field_class_name in ("ListField", "JSONArrayField"):
        child = getattr(field, "child", None)
        if child:
            return [_generate_mock_value_for_serializer_field("item", child)]
        return ["sample_item"]

    elif field_class_name in ("DictField", "JSONField"):
        return {"key": "value"}

    elif field_class_name in ("Serializer", "ModelSerializer"):
        return infer_body_from_serializer(field.__class__)

    elif field_class_name in ("ListSerializer",):
        child_serializer = getattr(field, "child", None)
        if child_serializer:
            return [infer_body_from_serializer(child_serializer.__class__)]
        return []

    # Fallback
    return f"sample_{field_name}"


def _generate_mock_value_for_form_field(field_name: str, field: Any) -> Any:
    field_class_name = field.__class__.__name__

    if field_class_name in ("CharField", "RegexField"):
        return f"test_{field_name}"
    elif field_class_name == "EmailField":
        return f"test_{field_name}@example.com"
    elif field_class_name == "IntegerField":
        return 1
    elif field_class_name in ("FloatField", "DecimalField"):
        return 1.0
    elif field_class_name == "BooleanField":
        return True
    elif field_class_name in ("ChoiceField", "ModelChoiceField"):
        choices = list(getattr(field, "choices", []))
        if choices and len(choices) > 0:
            val = choices[0][0]
            if val != "":
                return val
        return 1
    return f"sample_{field_name}"


def _is_empty_symbol(val: Any) -> bool:
    name = getattr(val, "__name__", "") or str(val)
    return "empty" in name.lower() or name == "empty"
