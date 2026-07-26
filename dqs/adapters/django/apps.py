from django.apps import AppConfig

class DQSConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dqs.adapters.django"
    verbose_name = "Django Query Sandbox Adapter"