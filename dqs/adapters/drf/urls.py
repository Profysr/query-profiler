"""
Da Profiler — URL Configuration

To mount the API in your Django project, add to your root urls.py:

    from django.urls import path, include

    if settings.DEBUG:
        urlpatterns += [
            path("dqs/", include("dqs.adapters.drf.urls")),
        ]

This exposes:
  GET  /dqs/           → List all discoverable routes (JSON)
  POST /dqs/profile/   → Profile a specific route
  GET  /dqs/health/    → Health check & configuration status
"""
from django.urls import path

from dqs.adapters.drf.views import DQSDashboardView, DQSProfileView, DQSHealthView

app_name = "drf"

urlpatterns = [
    path("", DQSDashboardView.as_view(), name="dashboard"),
    path("profile/", DQSProfileView.as_view(), name="profile"),
    path("health/", DQSHealthView.as_view(), name="health"),
]