"""
tests/adapters/drf/test_converters.py
=======================================
Unit tests for PathConverterResolver — the canonical path resolution engine.
Marker: `django` + `drf` (requires Django settings, no DB writes needed).
"""
import pytest
from unittest.mock import MagicMock
from dqs.adapters.drf.converters import PathConverterResolver
from dqs.adapters.drf.introspector import PathParam, RouteMetadata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def make_route(path, view_name="", target_model=None, path_params=None):
    return RouteMetadata(
        path=path,
        methods=["GET"],
        view_name=view_name,
        view_type="DRF_APIView",
        target_model=target_model,
        path_params=path_params or [],
    )


# ---------------------------------------------------------------------------
# resolve_converter_type
# ---------------------------------------------------------------------------

def test_resolve_known_converter_int():
    assert PathConverterResolver.resolve_converter_type("int") == "int"


def test_resolve_unknown_converter_returns_input():
    result = PathConverterResolver.resolve_converter_type("mycustomtype")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# generate_synthetic_fallback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("converter,expected", [
    ("int",    1),
    ("integer", 1),
    ("uuid",   "123e4567-e89b-12d3-a456-426614174000"),
    ("slug",   "test-slug"),
    ("str",    "test-param"),
    ("path",   "test-param"),
])
def test_generate_synthetic_fallback(converter, expected):
    result = PathConverterResolver.generate_synthetic_fallback("param", converter)
    assert result == expected


def test_generate_synthetic_fallback_slug_in_name():
    """With converter='str' but param name containing 'slug', result should be 'test-slug'."""
    result = PathConverterResolver.generate_synthetic_fallback("article_slug", "str")
    assert result == "test-slug"


# ---------------------------------------------------------------------------
# extract_from_model_instance
# ---------------------------------------------------------------------------

def test_extract_pk_from_model_instance():
    instance = MagicMock()
    instance.pk = 42
    result = PathConverterResolver.extract_from_model_instance(instance, "pk")
    assert result == 42


def test_extract_via_lookup_map():
    """lookup_url_kwarg='article_slug' should resolve to instance.slug via lookup_map."""
    instance = MagicMock()
    instance.slug = "django-guide"
    result = PathConverterResolver.extract_from_model_instance(
        instance, "article_slug", lookup_map={"article_slug": "slug"}
    )
    assert result == "django-guide"


def test_extract_falls_back_to_pk_if_attr_missing():
    """When attribute doesn't exist, should fall back to pk."""
    instance = MagicMock(spec=["pk"])
    instance.pk = 7
    result = PathConverterResolver.extract_from_model_instance(instance, "nonexistent_field")
    assert result == 7


# ---------------------------------------------------------------------------
# render_concrete_url
# ---------------------------------------------------------------------------

def test_render_concrete_url_via_reverse(settings):
    """render_concrete_url should produce a resolvable URL via Django's reverse."""
    # Use a known URL name from the demo app
    route = make_route(path="/books-cbv/<int:pk>/", view_name="book-detail-cbv")
    url = PathConverterResolver.render_concrete_url(route, {"pk": 1})
    assert "/books-cbv/1/" in url


def test_render_concrete_url_path_substitution_fallback():
    """When reverse() fails, fallback substitution must replace <int:pk> correctly."""
    route = make_route(path="/books/<int:pk>/", view_name="nonexistent-view-name")
    url = PathConverterResolver.render_concrete_url(route, {"pk": 99})
    assert url == "/books/99/"


def test_render_concrete_url_slug_substitution():
    route = make_route(path="/articles/<slug:article_slug>/", view_name="nonexistent")
    url = PathConverterResolver.render_concrete_url(route, {"article_slug": "my-article"})
    assert url == "/articles/my-article/"


# ---------------------------------------------------------------------------
# resolve_params_for_route (no model, synthetic only)
# ---------------------------------------------------------------------------

def test_resolve_params_synthetic_when_no_model():
    """Without a target_model, all params should be filled by synthetic fallback."""
    route = make_route(
        path="/items/<int:pk>/",
        path_params=[PathParam(name="pk", converter="int")],
    )
    resolved, created = PathConverterResolver.resolve_params_for_route(route)
    assert resolved["pk"] == 1
    assert created is None
