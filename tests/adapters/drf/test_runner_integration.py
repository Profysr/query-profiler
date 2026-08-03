import pytest
from dqs.adapters.drf.runner import DjangoSandboxRunner
from sample_app.models import Book

@pytest.mark.django_db
def test_profile_callable_setup_isolation():
    def setup_mock_data():
        # This bulk insert MUST NOT be captured by the interceptor
        Book.objects.bulk_create([Book(title=f"Book {i}") for i in range(50)])

    def code_to_profile():
        # This single SELECT MUST be captured
        return list(Book.objects.all())

    runner = DjangoSandboxRunner()
    
    # Run the profiler with the setup phase
    result = runner.profile_callable(code_to_profile, setup=setup_mock_data)
    
    # Assertions
    queries = result["queries"]
    
    # If the setup isolation failed, we'd have INSERT queries or a high query count here
    assert len(queries) == 1
    assert "SELECT" in queries[0]["sql"].upper()
    
    # Ensure the transaction rollback worked correctly (sandbox stayed isolated)
    assert Book.objects.count() == 0