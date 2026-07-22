from django.apps import AppConfig


class IotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.IoT"
    label = "iot"
    verbose_name = "IoT"

    def ready(self) -> None:
        from . import mqtt_handlers  # noqa: F401
