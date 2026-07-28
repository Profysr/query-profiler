# dqs/adapters/django/apps.py
from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

class DQSConfig(AppConfig):
    name = 'dqs.adapters.django'
    label = 'dqs_django'
    verbose_name = 'DQS Agentic Profiler'

    def ready(self):
        # Hard stop: DQS must never run in production.
        if not getattr(settings, 'DEBUG', False):
            raise ImproperlyConfigured(
                "DQS is loaded but DEBUG is False. DQS is a profiling and "
                "sandbox tool that must strictly be run in development environments."
            )