import pytest
from dqs.adapters.django.introspector import DjangoIntrospector

def test_list_routes_returns_list():
    introspector = DjangoIntrospector()
    routes = introspector.list_routes()
    assert isinstance(routes, list)
    
    for route in routes:
        assert "path" in route
        assert "methods" in route
        assert "view_name" in route
        assert "is_drf" in route
        assert not route["path"].startswith("/dqs/")