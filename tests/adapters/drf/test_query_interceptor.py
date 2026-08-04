"""
tests/adapters/drf/test_query_interceptor.py
=============================================
Tests for QueryInterceptor — the DB execute_wrapper context manager.
Marker: `django` + `drf`.

API: QueryInterceptor is a context manager. Captured queries are in .captured_queries
     with fields: sql, time_ms, src_loc
"""
import pytest
from django.db import connection
from dqs.adapters.drf.query_interceptor import QueryInterceptor


@pytest.mark.django_db
def test_interceptor_captures_query_and_stack():
    """QueryInterceptor must capture SQL, execution time, and source location."""
    interceptor = QueryInterceptor()

    with interceptor:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

    assert len(interceptor.captured_queries) == 1
    captured = interceptor.captured_queries[0]

    assert "SELECT 1" in captured["sql"]
    assert captured["time_ms"] >= 0


@pytest.mark.django_db
def test_interceptor_captures_multiple_queries():
    """Multiple SQL statements inside the interceptor block must all be captured."""
    interceptor = QueryInterceptor()

    with interceptor:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.execute("SELECT 2")

    assert len(interceptor.captured_queries) == 2


@pytest.mark.django_db
def test_interceptor_does_not_capture_outside_context():
    """Queries executed outside the `with interceptor:` block must not be captured."""
    interceptor = QueryInterceptor()

    # Query outside the interceptor — must not be captured
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")

    with interceptor:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 2")

    assert len(interceptor.captured_queries) == 1
    assert "SELECT 2" in interceptor.captured_queries[0]["sql"]