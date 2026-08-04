"""
tests/core/conftest.py – Core test suite configuration.

All tests in this package are pure Python (no Django, no ORM, no DB).
They exercise dqs/core/ only: SQL AST fingerprinting, N+1 analysis, and static AST scanning.
"""
import pytest

# Mark every test in this package as `core` automatically.
# Individual tests do not need to add @pytest.mark.core manually.
pytestmark = pytest.mark.core
