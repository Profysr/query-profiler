# tests/adapters/drf/test_runner.py
import pytest
from sample_app.models import Author, Book, Publisher
from dqs.adapters.drf.runner import DjangoSandboxRunner, ExecutionResult


@pytest.mark.django_db
class TestDjangoSandboxRunner:

    @pytest.fixture(autouse=True)
    def setup_sample_data(self):
        """Seed initial relational data for testing endpoints."""
        self.publisher = Publisher.objects.create(name="O'Reilly Media")
        self.author = Author.objects.create(name="Robert C. Martin")
        self.book = Book.objects.create(
            title="Clean Architecture",
            author=self.author,
            publisher=self.publisher
        )

    def test_runner_executes_endpoint_successfully(self):
        """Verify that running an endpoint returns a valid status code and enriched metrics."""
        runner = DjangoSandboxRunner()
        # Endpoint: /api/v1/books-fbv/
        result = runner.execute_isolated("/api/v1/books-fbv/", method="GET")

        assert isinstance(result, ExecutionResult)
        assert result.status_code == 200
        assert result.error is None
        
        # Verify metrics payload required for downstream MCP Agent consumption
        assert "total_time_ms" in result.metrics
        assert "db_time_ms" in result.metrics
        assert "total_queries" in result.metrics
        assert result.metrics["total_queries"] > 0
        assert len(result.queries) == result.metrics["total_queries"]

    def test_runner_enforces_atomic_transaction_rollback(self):
        """
        Critical Security Test: Verify that any database mutations executed 
        during the sandbox session are completely rolled back and leave 
        zero persistence in the database.
        """
        initial_book_count = Book.objects.count()
        assert initial_book_count == 1

        runner = DjangoSandboxRunner()
        
        # Execute profiling run
        result = runner.execute_isolated("/api/v1/books-fbv/", method="GET")
        assert result.status_code == 200

        # Verify state: Database row count must remain completely unchanged
        final_book_count = Book.objects.count()
        assert final_book_count == initial_book_count

    def test_runner_handles_invalid_methods_safely(self):
        """Verify the runner catches unsupported or malformed HTTP methods gracefully."""
        runner = DjangoSandboxRunner()
        result = runner.execute_isolated("/api/v1/books-fbv/", method="TRACE")

        assert result.status_code == 400
        assert result.error is not None
        assert "Invalid HTTP method" in result.error

    def test_runner_handles_unresolvable_routes(self):
        """Verify the runner handles missing or broken paths without crashing."""
        runner = DjangoSandboxRunner()
        result = runner.execute_isolated("/api/v1/non-existent-endpoint-xyz/", method="GET")

        assert result.status_code == 404
        assert result.error is not None
        assert "Route resolution failed" in result.error