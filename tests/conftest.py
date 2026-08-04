"""
Root conftest.py – Shared fixtures and pytest configuration for the full test suite.
"""
import pytest


def pytest_configure(config):
    """Register custom markers so pytest does not emit PytestUnknownMarkWarning."""
    config.addinivalue_line("markers", "core: Pure Python tests – no DB, no Django, no framework overhead")
    config.addinivalue_line("markers", "django: Tests requiring Django settings, ORM, and DB access")
    config.addinivalue_line("markers", "drf: Tests for the Django REST Framework adapter specifically")
    config.addinivalue_line("markers", "sqlalchemy: Tests for a SQLAlchemy adapter (future)")
