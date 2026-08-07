import contextlib
import threading

SHADOW_DB_ALIAS = "dqs_shadow"

# Capped seeding thresholds: seed up to SEED_MAX_CAP records when count < SEED_MIN_THRESHOLD
SEED_MIN_THRESHOLD = 1
SEED_MAX_CAP = 50

# Thread-local storage to track active profiling session
_local = threading.local()


class DQSRouter:
    @classmethod
    def set_active(cls, active: bool) -> None:
        _local.active = active

    @classmethod
    def is_active(cls) -> bool:
        return getattr(_local, "active", False)

    def db_for_read(self, model, **hints):
        if self.is_active():
            return SHADOW_DB_ALIAS
        return None

    def db_for_write(self, model, **hints):
        if self.is_active():
            return SHADOW_DB_ALIAS
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if self.is_active():
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == SHADOW_DB_ALIAS:
            return True
        if self.is_active():
            return db == SHADOW_DB_ALIAS
        return None


@contextlib.contextmanager
def profiling_session():
    """
    Context manager to safely activate and deactivate shadow database routing
    for the current thread.
    """
    DQSRouter.set_active(True)
    try:
        yield
    finally:
        DQSRouter.set_active(False)
