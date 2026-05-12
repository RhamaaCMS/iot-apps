from django.apps import AppConfig


class IotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.IoT"
    label = "iot"
    verbose_name = "IoT"

    def ready(self) -> None:
        from apps.mqtt.signals import mqtt_message_received
        from apps.IoT.mqtt_handlers import on_mqtt_incoming

        mqtt_message_received.connect(
            on_mqtt_incoming, dispatch_uid="iot_mqtt_uplink"
        )
