"""Bridge apps.mqtt signals to IoT ingest."""

import logging

from django.dispatch import receiver

from apps.mqtt.signals import mqtt_message_received

logger = logging.getLogger(__name__)


@receiver(mqtt_message_received, dispatch_uid="iot_mqtt_uplink")
def on_mqtt_incoming(sender, topic: str, payload: str, qos: int, **kwargs) -> None:
    from .services import process_incoming_mqtt_message

    result = process_incoming_mqtt_message(topic, payload)
    if result and not result.startswith("skip:"):
        logger.debug("IoT: topic=%r -> %s", topic, result)
