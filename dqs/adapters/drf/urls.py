"""
Da Profiler — URL Configuration

To mount the dashboard in your Django project, add to your root urls.py:

    from django.urls import path, include

    if settings.DEBUG:
        urlpatterns += [
            path("dqs/", include("dqs.adapters.drf.urls")),
        ]

This exposes:
  GET  /dqs/          → Developer dashboard
  POST /dqs/profile/  → AJAX sandbox profiling endpoint
"""
from django.urls import path

from dqs.adapters.drf.views import DQSDashboardView, DQSProfileView

app_name = "dqs"

urlpatterns = [
    path("", DQSDashboardView.as_view(), name="dashboard"),
    path("profile/", DQSProfileView.as_view(), name="profile"),
]
