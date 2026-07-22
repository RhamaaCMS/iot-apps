from django.urls import path

from .ota_public_views import ota_public_download

app_name = "iot_ota"

urlpatterns = [
    path("firmware/", ota_public_download, name="firmware_download"),
]
