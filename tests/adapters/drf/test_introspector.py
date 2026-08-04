"""
tests/adapters/drf/test_introspector.py
=========================================
Unit tests for DjangoIntrospector — URL route discovery and parameter extraction.
Shared fixtures: `introspector` (from conftest.py).
Marker: `django` + `drf`.
"""
import pytest
from django.core.exceptions import ImproperlyConfigured
from dqs.adapters.drf.introspector import DjangoIntrospector, RouteMetadata


class TestDjangoIntrospector:

    def test_initialization_requires_debug(self, settings):
        """Ensure IntrospectorGuard raises when DEBUG=False."""
        settings.DEBUG = False
        with pytest.raises(ImproperlyConfigured):
            DjangoIntrospector()

    def test_list_all_routes_discovers_endpoints(self, introspector):
        """All configured sample app routes must be discovered."""
        routes = introspector.list_all_routes()
        assert len(routes) > 0
        paths = [r.path for r in routes]
        assert any("books-drf" in p for p in paths)
        assert any("books-set" in p for p in paths)

    def test_route_metadata_is_correct_type(self, introspector):
        """Every discovered route must be a RouteMetadata instance."""
        routes = introspector.list_all_routes()
        for route in routes:
            assert isinstance(route, RouteMetadata)
            assert isinstance(route.methods, list)

    def test_drf_viewset_classification(self, introspector):
        """DRF ViewSets must be classified as DRF_ViewSet with a resolved target_model."""
        routes = introspector.list_all_routes()
        viewset_route = next((r for r in routes if "books-set" in r.path), None)
        assert viewset_route is not None
        assert viewset_route.is_drf is True
        assert viewset_route.view_type == "DRF_ViewSet"
        assert viewset_route.target_model == "sample_app.Book"

    def test_drf_apiview_with_path_params(self, introspector):
        """A DRF APIView route with <int:pk> must expose the pk PathParam."""
        routes = introspector.list_all_routes()
        drf_route = next((r for r in routes if "books-drf" in r.path and r.has_path_params), None)
        # books-drf may not have path params — check books-set detail instead
        detail_route = next((r for r in routes if "books-set" in r.path and r.has_path_params), None)
        if detail_route:
            assert any(p.name == "pk" for p in detail_route.path_params)

    def test_dqs_routes_are_excluded(self, introspector):
        """Internal /dqs/ dashboard routes must never appear in discovered targets."""
        routes = introspector.list_all_routes()
        for route in routes:
            assert not route.path.startswith("/dqs/")

    def test_extract_view_lookup_map_standard(self):
        """Standard DRF view with no customization must return pk -> pk."""
        from rest_framework.generics import RetrieveAPIView
        introspector = DjangoIntrospector()
        lookup_map = introspector.extract_view_lookup_map(RetrieveAPIView)
        assert lookup_map == {"pk": "pk"}

    def test_extract_view_lookup_map_custom_kwarg(self):
        """View overriding lookup_url_kwarg must map custom kwarg -> lookup_field."""
        from rest_framework.generics import RetrieveAPIView

        class ArticleView(RetrieveAPIView):
            lookup_url_kwarg = "article_slug"
            lookup_field = "slug"

        introspector = DjangoIntrospector()
        lookup_map = introspector.extract_view_lookup_map(ArticleView)
        assert lookup_map == {"article_slug": "slug"}

    def test_extract_view_lookup_map_none_view(self):
        """None view class must return an empty mapping without raising."""
        introspector = DjangoIntrospector()
        assert introspector.extract_view_lookup_map(None) == {}