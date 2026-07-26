import os
import django
from django.conf import settings

def pytest_configure(config):
    """
    Hook that runs before tests in this directory are executed.
    Initializes Django ONLY for adapter tests.
    """
    if not settings.configured:
        os.environ.setdefault(
            "DJANGO_SETTINGS_MODULE", 
            "demos.django.demo_project.config.settings"
        )
        django.setup()