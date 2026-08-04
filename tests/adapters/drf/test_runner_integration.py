"""
tests/adapters/drf/test_runner_integration.py
===============================================
Integration test verifying that the profile_callable() setup phase is fully
isolated from the query interceptor, seeding queries must never pollute
the N+1 capture window.
Marker: `django` + `drf`.
"""
import pytest
from sample_app.models import Author, Book, Publisher
from dqs.adapters.drf.runner import DjangoSandboxRunner


@pytest.mark.django_db(transaction=True)
def test_profile_callable_setup_queries_are_not_captured(runner):
    """
    Validates the core isolation guarantee:
    - INSERT queries fired during setup() must NOT appear in captured_queries.
    - Only the SELECT inside the profiled callable must be captured.
    - After execution, the DB must be fully rolled back to zero rows.
    """
    def seed_books():
        publisher = Publisher.objects.create(name="Seed Publisher")
        author = Author.objects.create(name="Seed Author")
        Book.objects.bulk_create([
            Book(title=f"Book {i}", author=author, publisher=publisher)
            for i in range(10)
        ])

    def profiled_query():
        return list(Book.objects.all())

    result, queries, db_duration, _ = runner.profile_callable(profiled_query, setup=seed_books)

    # Only the single SELECT must be captured — setup INSERTs must be invisible
    sql_statements = [q["sql"].upper() for q in queries]
    assert len(queries) == 1, f"Expected 1 captured query, got {len(queries)}: {sql_statements}"
    assert "SELECT" in sql_statements[0]
    assert not any("INSERT" in sql for sql in sql_statements)

    # Savepoint rollback must leave the database in its original state
    assert Book.objects.count() == 0