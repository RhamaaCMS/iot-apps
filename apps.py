from django.apps import AppConfig


class IotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.IoT"
    label = "iot"
    verbose_name = "IoT"

    def ready(self) -> None:
        from . import mqtt_handlers  # noqa: F401
        from apps.mqtt.worker_registry import register_default_topic, register_worker_task
        from .integrations.mqtt import run_outbox_loop

        register_worker_task(run_outbox_loop)
        register_default_topic("iot/v1/+/+/up/#")
