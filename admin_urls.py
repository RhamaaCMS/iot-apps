"""Routes mounted under /admin/iot/ via wagtail_hooks."""

from django.urls import path

from . import admin_views

app_name = "iot"

urlpatterns = [
    path("", admin_views.dashboard, name="dashboard"),
    path(
        "organizations/",
        admin_views.panel_organizations,
        name="panel_organizations",
    ),
    path(
        "memberships/",
        admin_views.panel_memberships,
        name="panel_memberships",
    ),
    path("devices/", admin_views.panel_devices, name="panel_devices"),
    path(
        "api/device/<int:device_pk>/mqtt-messages/",
        admin_views.api_device_mqtt_messages,
        name="api_device_mqtt_messages",
    ),
    path("api/mqtt/bridge-status/", admin_views.api_mqtt_bridge_status, name="api_mqtt_bridge"),
    path("api/devices/summary/", admin_views.api_devices_summary, name="api_devices_summary"),
    path("api/envelope/preview/", admin_views.api_envelope_preview, name="api_envelope_preview"),
    path("ota/", admin_views.panel_ota, name="panel_ota"),
]
