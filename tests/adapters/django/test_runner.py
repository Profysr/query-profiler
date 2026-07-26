# tests/adapters/django/test_runner.py

import json
import pytest
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.test import override_settings

from dqs.adapters.django.runner import DjangoSandboxRunner
from config.models import Author, Book
from config.views import EmailSendingCBV, NPlusOneBookListView


@pytest.mark.django_db
class TestDjangoSandboxRunner:

    def test_cbv_side_effect_regression(self):
        """
        REGRESSION TEST: Ensures _detect_side_effects checks .view_class so
        plain Django CBVs wrapped via .as_view() have their send_mail calls flagged.
        """
        runner = DjangoSandboxRunner()
        view_func = EmailSendingCBV.as_view()

        warnings = runner._detect_side_effects(view_func)

        print("\n" + "=" * 50)
        print("🔍 DETECTED SIDE EFFECTS OUTPUT:")
        print(json.dumps(warnings, indent=2))
        print("=" * 50)

        assert len(warnings) == 1
        assert "send_mail" in warnings[0]

    def test_captures_n_plus_one_queries(self):
        """Verifies query count capture on NPlusOneBookListView."""
        author = Author.objects.create(name="J.R.R. Tolkien")
        for title in ["The Hobbit", "The Fellowship of the Ring", "The Two Towers"]:
            Book.objects.create(title=title, author=author)

        runner = DjangoSandboxRunner()

        with override_settings(DEBUG=True):
            result = runner.execute_isolated(
                view_func=NPlusOneBookListView,
                method="GET",
                path="/books/",
            )

        print("\n" + "=" * 50)
        print("📊 EXECUTE_ISOLATED OUTPUT STRUCTURE (N+1 VIEW):")
        print(json.dumps(result, indent=2))
        print("=" * 50)

        assert result["status_code"] == 200
        assert result["query_count"] == 4  # 1 initial + 3 loop queries
        assert len(result["queries"]) == 4

    def test_rolls_back_database_mutations(self):
        """Ensures DB changes inside execute_isolated are rolled back completely."""
        def mutating_view(request):
            Author.objects.create(name="Transient Author")
            return JsonResponse({"status": "created"}, status=201)

        runner = DjangoSandboxRunner()

        with override_settings(DEBUG=True):
            result = runner.execute_isolated(view_func=mutating_view, method="POST")

        print("\n" + "=" * 50)
        print("🔄 EXECUTE_ISOLATED OUTPUT STRUCTURE (MUTATING VIEW):")
        print(json.dumps(result, indent=2))
        print("=" * 50)

        assert result["status_code"] == 201
        assert not Author.objects.filter(name="Transient Author").exists()

    def test_handles_view_exceptions_gracefully(self):
        """Ensures a crashing view logs warnings instead of crashing the sandbox."""
        def broken_view(request):
            raise KeyError("Missing parameter 'user_id'")

        runner = DjangoSandboxRunner()

        with override_settings(DEBUG=True):
            result = runner.execute_isolated(view_func=broken_view)

        print("\n" + "=" * 50)
        print("⚠️ EXECUTE_ISOLATED OUTPUT STRUCTURE (EXCEPTIONAL VIEW):")
        print(json.dumps(result, indent=2))
        print("=" * 50)

        assert result["status_code"] == 500
        assert any("KeyError" in w for w in result["warnings"])

    def test_raises_permission_denied_when_debug_false(self):
        """Guardrail check for DEBUG=False."""
        runner = DjangoSandboxRunner()
        with override_settings(DEBUG=False):
            with pytest.raises(PermissionDenied):
                runner.execute_isolated(view_func=NPlusOneBookListView)