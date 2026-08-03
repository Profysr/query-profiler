import pytest
from django.db import connection
from dqs.adapters.drf.query_interceptor import QueryInterceptor

@pytest.mark.django_db
def test_interceptor_captures_query_and_stack():
    interceptor = QueryInterceptor()
    
    with connection.execute_wrapper(interceptor):
        # Trigger a simple raw query
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    
    assert len(interceptor.queries) == 1
    captured = interceptor.queries[0]
    
    assert "SELECT 1" in captured["sql"]
    assert captured["duration"] >= 0
    assert "test_query_interceptor.py" in captured["origin_file"]
    assert "test_interceptor_captures_query_and_stack" in captured["origin_function"]
    assert captured["origin_line"] > 0