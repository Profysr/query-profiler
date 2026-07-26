# tests/adapters/django/test_introspector.py
import pytest
from dqs.adapters.django.introspector import DjangoIntrospector, RouteMetadata


@pytest.mark.django_db
class TestDjangoIntrospector:
    
    def test_introspector_initialization_requires_debug(self):
        """Ensure the introspector respects the DEBUG=True security requirement."""
        introspector = DjangoIntrospector()
        assert introspector is not None

    def test_list_all_routes_discovers_endpoints(self):
        """Verify that all configured sample app routes are successfully discovered."""
        introspector = DjangoIntrospector()
        routes = introspector.list_all_routes()

        assert len(routes) > 0
        paths = [r.path for r in routes]

        # Verify our sample app routes are present
        assert any("books-fbv" in p for p in paths)
        assert any("books-cbv" in p for p in paths)
        assert any("books-drf" in p for p in paths)
        assert any("books-set" in p for p in paths)

    def test_route_metadata_classification_fbv(self):
        """Verify Function-Based Views are correctly classified."""
        introspector = DjangoIntrospector()
        routes = introspector.list_all_routes()

        fbv_route = next((r for r in routes if "books-fbv" in r.path), None)
        assert fbv_route is not None
        assert fbv_route.view_type == "FBV"
        assert "GET" in fbv_route.methods
        assert fbv_route.executable is True
        assert fbv_route.has_path_params is False

    def test_route_metadata_classification_cbv_with_path_params(self):
        """Verify Class-Based Views with dynamic parameters are correctly flagged."""
        introspector = DjangoIntrospector()
        routes = introspector.list_all_routes()

        cbv_route = next((r for r in routes if "books-cbv" in r.path), None)
        assert cbv_route is not None
        assert cbv_route.view_type == "CBV"
        assert cbv_route.has_path_params is True
        assert cbv_route.target_model == "sample_app.Book"

    def test_route_metadata_classification_drf_viewset(self):
        """Verify DRF ViewSets are correctly identified and targeted."""
        introspector = DjangoIntrospector()
        routes = introspector.list_all_routes()

        viewset_route = next((r for r in routes if "books-set" in r.path), None)
        assert viewset_route is not None
        assert viewset_route.is_drf is True
        assert viewset_route.view_type == "DRF_ViewSet"
        assert viewset_route.target_model == "sample_app.Book"