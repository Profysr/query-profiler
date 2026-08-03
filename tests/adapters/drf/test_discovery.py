import pytest
from django.db.models.signals import post_save
from django.dispatch import receiver
from dqs.adapters.drf.discovery import DjangoTargetDiscovery
from sample_app.models import Book
from django.test import override_settings

# Dummy signal to discover
@receiver(post_save, sender=Book)
def dummy_notification_signal(sender, instance, **kwargs):
    pass

@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_discovers_registered_signals():
    discovery = DjangoTargetDiscovery()
    targets = discovery.discover_all()
    
    signal_targets = [t for t in targets if t.kind == "signal"]
    
    assert len(signal_targets) >= 1
    assert any("dummy_notification_signal" in t.id for t in signal_targets)
    
    # Ensure they are marked as triggerable for the upcoming v0.3 phase
    for target in signal_targets:
        if "dummy_notification_signal" in target.id:
            assert target.triggerable is True