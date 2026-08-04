"""
tests/adapters/drf/test_runner.py
===================================
Integration tests for DjangoSandboxRunner.
Shared fixtures: `runner`, `seeded_book` (from conftest.py).
Marker: `django` + `drf`.
"""
import pytest
from sample_app.models import Book
from dqs.adapters.drf.runner import DjangoSandboxRunner, ExecutionResult


class TestDjangoSandboxRunner:

    def test_runner_executes_list_endpoint_successfully(self, runner, seeded_book):
        """A GET to a list endpoint must return 200 with metrics and captured queries."""
        result = runner.execute_isolated("/api/v1/books-fbv/", method="GET")

        assert isinstance(result, ExecutionResult)
        assert result.status_code == 200
        assert result.error is None
        assert "total_time_ms" in result.metrics
        assert "db_time_ms" in result.metrics
        assert "total_queries" in result.metrics
        assert result.metrics["total_queries"] > 0
        assert len(result.queries) == result.metrics["total_queries"]

    def test_atomic_transaction_rollback(self, runner, seeded_book):
        """
        Critical safety test: any DB mutations during profiling must be fully rolled back.
        The Book count before and after a profiling run must be identical.
        """
        count_before = Book.objects.count()
        result = runner.execute_isolated(
            "/api/v1/books-fbv/", method="GET", seed_count=5, target_model="sample_app.Book"
        )
        assert result.status_code == 200
        assert Book.objects.count() == count_before

    def test_invalid_http_method_returns_400(self, runner):
        """An unsupported HTTP method must return status 400 without crashing."""
        result = runner.execute_isolated("/api/v1/books-fbv/", method="TRACE")
        assert result.status_code == 400
        assert result.error is not None
        assert "Invalid HTTP method" in result.error

    def test_unresolvable_route_returns_404(self, runner):
        """A path that cannot be resolved must return status 404 with an error message."""
        result = runner.execute_isolated("/this/does/not/exist/", method="GET")
        assert result.status_code == 404
        assert result.error is not None

    def test_seeded_records_are_present_in_result(self, runner):
        """When seed_count > 0, the ExecutionResult must contain seeded_records."""
        result = runner.execute_isolated(
            "/api/v1/books-fbv/", method="GET", seed_count=3, target_model="sample_app.Book"
        )
        assert isinstance(result.seeded_records, list)
        assert len(result.seeded_records) == 3


class TestStepDrivenPipeline:
    """Tests for the observable MCP/agent-friendly step-by-step pipeline entries."""

    def test_probe_route_step_returns_exists_true(self, runner, seeded_book):
        """probe_route_step on a valid route must report exists=True."""
        result = runner.probe_route_step("/api/v1/books-fbv/")
        assert result["exists"] is True
        assert result["status_code"] < 400

    def test_probe_route_step_returns_exists_false(self, runner):
        """probe_route_step on a nonexistent path must report exists=False."""
        result = runner.probe_route_step("/nonexistent-path-xyz/")
        assert result["exists"] is False

    def test_seed_resource_step_creates_records(self, runner, db):
        """seed_resource_step must create records and report seeded=True."""
        result = runner.seed_resource_step("sample_app.Book", seed_count=2)
        assert result["seeded"] is True
        assert result["seeded_count"] == 2
        assert len(result["instances"]) == 2

    def test_seed_resource_step_invalid_model(self, runner, db):
        """seed_resource_step with a bad model string must not crash — return seeded=False."""
        result = runner.seed_resource_step("invalid.Model", seed_count=1)
        assert result["seeded"] is False
        assert "error" in result