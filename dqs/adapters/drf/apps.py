# dqs/adapters/drf/apps.py
from pathlib import Path

from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class DQSConfig(AppConfig):
    name = 'dqs.adapters.drf'
    label = 'dqs_drf'
    verbose_name = 'DQS Agentic Profiler'
    # Explicitly set the path to resolve the namespace package multiple locations conflict
    path = str(Path(__file__).resolve().parent)

    def ready(self):
        # Hard stop: DQS must never run in production.
        if not getattr(settings, 'DEBUG', False):
            raise ImproperlyConfigured(
                "DQS is loaded but DEBUG is False. DQS is a profiling and "
                "sandbox tool that must strictly be run in development environments."
            )