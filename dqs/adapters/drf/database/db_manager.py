import logging
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command

from dqs.adapters.drf.router import SHADOW_DB_ALIAS

logger = logging.getLogger("dqs.runner")

class ShadowDatabaseManager:
    """Validates shadow database configuration and manages setup prerequisites."""

    _validated: ClassVar[bool] = False
    ROUTER_PATH: ClassVar[str] = "dqs.adapters.drf.router.DQSRouter"

    @classmethod
    def validate_configuration(cls) -> None:
        """
        Validates that required DQS database settings and routers are 
        explicitly defined in Django settings.
        """
        if cls._validated:
            return

        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("DaProfiler requires DEBUG=True for safety.")

        cls._validate_shadow_db_settings()
        cls._validate_router_settings()

        cls._validated = True

    @classmethod
    def _validate_shadow_db_settings(cls) -> None:
        """Ensures SHADOW_DB_ALIAS is defined in settings.DATABASES."""
        if SHADOW_DB_ALIAS not in settings.DATABASES:
            raise ImproperlyConfigured(
                f"[DaProfiler Setup Error] Shadow database '{SHADOW_DB_ALIAS}' is not defined in settings.DATABASES.\n"
                f"Please add a '{SHADOW_DB_ALIAS}' entry to DATABASES in your settings.py."
            )

    @classmethod
    def _validate_router_settings(cls) -> None:
        """Ensures DQSRouter is listed in settings.DATABASE_ROUTERS."""
        routers = getattr(settings, "DATABASE_ROUTERS", [])
        if cls.ROUTER_PATH not in routers:
            raise ImproperlyConfigured(
                f"[DaProfiler Setup Error] '{cls.ROUTER_PATH}' is missing from settings.DATABASE_ROUTERS.\n"
                f"Please add '{cls.ROUTER_PATH}' as the first entry in DATABASE_ROUTERS in your settings.py."
            )

    @staticmethod
    def run_migrations() -> None:
        """Optional programmatic helper to run migrations on the shadow database."""
        try:
            call_command("migrate", database=SHADOW_DB_ALIAS, interactive=False, verbosity=0)
        except Exception as e:
            logger.warning("Failed to run migrations on %s: %s", SHADOW_DB_ALIAS, e)