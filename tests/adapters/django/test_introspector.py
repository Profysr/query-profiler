# tests/adapters/django/test_introspector.py

import json
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from dqs.adapters.django.introspector import DjangoIntrospector


@pytest.mark.django_db
class TestDjangoIntrospector:

    def test_discovers_registered_routes(self):
        """Verifies that introspector walks url_patterns and finds HTTP routes."""
        introspector = DjangoIntrospector()

        with override_settings(DEBUG=True):
            all_routes = introspector.list_all_routes()

        print("\n" + "=" * 50)
        print("🗺️ INTROSPECTOR LIST_ALL_ROUTES OUTPUT STRUCTURE:")
        print(json.dumps(all_routes, indent=2))
        print("=" * 50)

        routes = all_routes["http"]
        paths = [r["path"] for r in routes]
        assert "/books/" in paths
        assert "/books/<int:pk>/" in paths
        # assert "/books/<int:pk>/book_detail/<uuid:book_id>/" in paths
        assert "/send-email/" in paths

    def test_flags_path_parameters(self):
        """Verifies that endpoints with path parameters get has_path_params=True."""
        introspector = DjangoIntrospector()

        with override_settings(DEBUG=True):
            routes = introspector.list_all_routes()["http"]

        detail_route = next(r for r in routes if r["path"] == "/books/<int:pk>/")

        print("\n" + "=" * 50)
        print("📌 ROUTE WITH PATH PARAMS METADATA:")
        print(json.dumps(detail_route, indent=2))
        print("=" * 50)

        assert detail_route["has_path_params"] is True

    def test_identifies_django_cbv_methods(self):
        """Ensures Django CBVs extract supported methods like GET."""
        introspector = DjangoIntrospector()

        with override_settings(DEBUG=True):
            routes = introspector.list_all_routes()["http"]

        email_route = next(r for r in routes if r["path"] == "/send-email/")

        print("\n" + "=" * 50)
        print("🏫 DJANGO CBV ROUTE METADATA:")
        print(json.dumps(email_route, indent=2))
        print("=" * 50)

        assert email_route["view_type"] == "Django_CBV"
        assert "GET" in email_route["methods"]

    def test_raises_improperly_configured_when_debug_false(self):
        """Guardrail check for DEBUG=False."""
        introspector = DjangoIntrospector()
        with override_settings(DEBUG=False):
            with pytest.raises(ImproperlyConfigured):
                introspector.list_all_routes()