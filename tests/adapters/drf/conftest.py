# tests/adapters/django/conftest.py
import os
import sys
from pathlib import Path
import django
from django.conf import settings

# Dynamically add demos/django_app to sys.path at runtime.
# This allows 'sample_app' and 'demo_project' to be imported cleanly without polluting the root pyproject.toml or affecting other frameworks!
CURRENT_DIR = Path(__file__).resolve().parent

# .parents[0] is the parent (same as .parent) - django
# .parents[1] is the grandparent - adapters
# .parents[2] is the great-grandparent (3 levels up) - tests
DJANGO_APP_PATH = CURRENT_DIR.parents[2] / "demos" / "django_app"

if str(DJANGO_APP_PATH) not in sys.path:
    sys.path.insert(0, str(DJANGO_APP_PATH))

def pytest_configure(config):
    """
    Initializes Django settings and runtime exclusively for Django adapter tests.
    """
    if not settings.configured:
        os.environ.setdefault(
            "DJANGO_SETTINGS_MODULE", 
            "demo_project.config.settings"
        )
        django.setup()