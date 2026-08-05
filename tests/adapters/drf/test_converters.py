"""
tests/adapters/drf/test_converters.py
======================================
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


def test_extract_nested_relational_attribute():
    """Extract parent FK id via relational tree traversal."""
    parent = MagicMock()
    parent.pk = 99
    instance = MagicMock()
    instance.organization = parent
    
    result = PathConverterResolver.extract_from_model_instance(instance, "org_id")
    assert result == 99


# ---------------------------------------------------------------------------
# render_concrete_url
# ---------------------------------------------------------------------------

def test_render_concrete_url_via_reverse(settings):
    """render_concrete_url should produce a resolvable URL via Django's reverse."""
    route = make_route(path="/books-cbv/<int:pk>/", view_name="book-detail-cbv")
    url = PathConverterResolver.render_concrete_url(route, {"pk": 1})
    assert url == "/books-cbv/1/"


def test_render_concrete_url_via_path_substitution():
    """When view_name fails, should substitute <int:pk> in path directly."""
    route = make_route(path="/api/items/<int:pk>/", view_name="nonexistent_view_xyz")
    url = PathConverterResolver.render_concrete_url(route, {"pk": 42})
    assert url == "/api/items/42/"


# ---------------------------------------------------------------------------
# resolve_params_for_route without synthetic fallbacks
# ---------------------------------------------------------------------------

def test_resolve_params_unresolved_returns_empty():
    """Routes with missing path params and no model return unresolved params dictionary."""
    route = make_route(
        path="/api/custom/<int:custom_id>/",
        path_params=[PathParam(name="custom_id", converter="int")],
    )
    resolved, created = PathConverterResolver.resolve_params_for_route(
        route, auto_generate_if_missing=False
    )
    assert "custom_id" not in resolved
    assert created is None
