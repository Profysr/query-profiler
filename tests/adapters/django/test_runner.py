import pytest
from demo_project.sample_app.models import Author, Book
from demo_project.sample_app.views import NPlusOneBookListView
from dqs.adapters.django.runner import DjangoSandboxRunner


@pytest.mark.django_db
def test_execute_isolated_rollback():
    # Setup test DB records
    author = Author.objects.create(name="J.R.R. Tolkien")
    Book.objects.create(title="The Hobbit", author=author)

    runner = DjangoSandboxRunner()
    result = runner.execute_isolated(
        view_func=NPlusOneBookListView, method="GET", path="/books/"
    )

    assert result["status_code"] == 200
    assert result["query_count"] >= 2  # 1 for books + 1 for author FK
    assert isinstance(result["queries"], list)

    # Verify sandbox rollback guarantees no unintended side-effects persisted
    assert Author.objects.count() == 1