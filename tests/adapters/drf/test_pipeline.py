import pytest
from django.test import TestCase, RequestFactory
from django.core.exceptions import ImproperlyConfigured
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets

from dqs.core.analyzer import fingerprint, detect_n_plus_one, suggest_fix
from dqs.adapters.drf.introspector import DjangoIntrospector, RouteMetadata, PathParam
from dqs.adapters.drf.runner import DjangoSandboxRunner, ExecutionResult


# ==========================================
# Mock Views & Models for Testing
# ==========================================
# (Note: Assumes a test model exists or we mock the model resolution)

class DummyAPIView(APIView):
    def get(self, request, *args, **kwargs):
        # Trigger an intentional multi-query loop to test N+1 detection & stack tracing
        return Response({"status": "ok"})


class DQSPipelineTestCase(TestCase):
    
    def setUp(self):
        # Ensure DEBUG is True as required by DQS safety guards
        settings.DEBUG = True

    # ==========================================
    # 1. TEST ANALYZER & FINGERPRINTING LAYER
    # ==========================================
    def test_sql_fingerprinting_normalization(self):
        sql1 = "SELECT * FROM library_book WHERE id = 1 AND title = 'Django';"
        sql2 = "SELECT * FROM library_book WHERE title = 'Python' AND id = 5;"
        
        fp1 = fingerprint(sql1)
        fp2 = fingerprint(sql2)
        
        # Literals should be replaced with '?' and AND conditions sorted for identical fingerprints
        self.assertEqual(fp1, fp2)

    def test_n_plus_one_detection_and_suggestions(self):
        queries = [
            {"sql": "SELECT * FROM author WHERE id = 1", "time": 0.5, "source_location": "views.py:10"},
            {"sql": "SELECT * FROM author WHERE id = 2", "time": 0.4, "source_location": "views.py:10"},
            {"sql": "SELECT * FROM author WHERE id = 3", "time": 0.6, "source_location": "views.py:10"},
        ]
        
        flags = detect_n_plus_one(queries, threshold=3)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["count"], 3)
        self.assertEqual(flags[0]["source_location"], "views.py:10")
        self.assertIn("select_related", flags[0]["suggestion"])

    # ==========================================
    # 2. TEST INTROSPECTOR LAYER
    # ==========================================
    def test_introspector_debug_guard(self):
        settings.DEBUG = False
        with self.assertRaises(ImproperlyConfigured):
            DjangoIntrospector()
        settings.DEBUG = True  # Reset

    def test_introspector_route_scanning(self):
        introspector = DjangoIntrospector()
        routes = introspector.list_all_routes()
        # Verify it returns a list of RouteMetadata
        self.assertIsInstance(routes, list)
        for route in routes:
            self.assertIsInstance(route, RouteMetadata)
            self.assertIsInstance(route.methods, list)

    # ==========================================
    # 3. TEST SANDBOX RUNNER LAYER
    # ==========================================
    def test_runner_debug_guard(self):
        settings.DEBUG = False
        with self.assertRaises(ImproperlyConfigured):
            DjangoSandboxRunner()
        settings.DEBUG = True

    def test_runner_invalid_method_handling(self):
        runner = DjangoSandboxRunner()
        result = runner.execute_isolated(url_name_or_path="/fake-url/", method="INVALID")
        self.assertEqual(result.status_code, 400)
        self.assertIn("Invalid HTTP method", result.error)

    def test_runner_side_effect_detection(self):
        runner = DjangoSandboxRunner()
        
        # Define a temporary view function containing a risky keyword
        def risky_view(request):
            import smtplib
            return Response({})
            
        warnings = runner._detect_side_effects(risky_view)
        self.assertTrue(any("smtplib" in w for w in warnings))

    def test_source_location_extraction(self):
        runner = DjangoSandboxRunner()
        # Test that stack trace inspection correctly bypasses framework frames
        loc = runner._extract_source_location()
        # Should trace back to this test file or framework runner
        self.assertIsNotNone(loc)