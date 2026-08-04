"""
tests/adapters/drf/conftest.py – DRF adapter test suite configuration.

Sets up shared fixtures for DRF adapter tests including seeded relational model data,
a pre-configured DjangoSandboxRunner, and a DjangoIntrospector instance.
All tests in this package are automatically marked as both `django` and `drf`.
"""
import pytest
from django.conf import settings
from sample_app.models import Author, Book, Publisher
from dqs.adapters.drf.runner import DjangoSandboxRunner
from dqs.adapters.drf.introspector import DjangoIntrospector

# Auto-mark every test in this package as django + drf
pytestmark = [pytest.mark.django, pytest.mark.drf]


@pytest.fixture(autouse=True)
def enforce_debug_mode(settings):
    """Force DEBUG=True for all DRF adapter tests — required by DQS safety guards."""
    settings.DEBUG = True


@pytest.fixture
def seeded_book(db):
    """
    Creates a minimal but complete relational data set:
      Publisher -> Author -> Book
    Returns the Book instance for use in tests that require an existing DB record.
    """
    publisher = Publisher.objects.create(name="Test Publisher")
    author = Author.objects.create(name="Test Author")
    book = Book.objects.create(title="Test Book", author=author, publisher=publisher)
    return book


@pytest.fixture
def runner(db):
    """Returns a pre-initialized DjangoSandboxRunner for use in runner/pipeline tests."""
    return DjangoSandboxRunner()


@pytest.fixture
def introspector():
    """Returns a pre-initialized DjangoIntrospector for use in introspector tests."""
    return DjangoIntrospector()
