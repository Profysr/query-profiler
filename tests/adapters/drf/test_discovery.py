"""
tests/adapters/drf/test_discovery.py
======================================
Tests for DjangoTargetDiscovery — signal receiver discovery.
Marker: `django` + `drf`.
"""
import pytest
from django.db.models.signals import post_save
from dqs.adapters.drf.discovery import DjangoTargetDiscovery
from sample_app.models import Book
from django.test import override_settings


def dummy_notification_signal(sender, instance, **kwargs):
    pass


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_discovers_registered_signals():
    """
    DjangoTargetDiscovery must discover at least one post_save signal receiver.
    """
    post_save.connect(dummy_notification_signal, sender=Book)
    try:
        discovery = DjangoTargetDiscovery()
        targets = discovery.discover_all()

        signal_targets = [t for t in targets if t.kind == "signal"]

        # Assert specifically on signals, independent of global app routes/tasks
        assert len(signal_targets) >= 1
        assert any("dummy_notification_signal" in t.id for t in signal_targets)
    finally:
        post_save.disconnect(dummy_notification_signal, sender=Book)