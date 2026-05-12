"""
Bridge apps.mqtt signals to IoT ingest.
"""

import logging

logger = logging.getLogger(__name__)


def on_mqtt_incoming(sender, topic: str, payload: str, qos: int, **kwargs) -> None:
    from .services import process_incoming_mqtt_message

    result = process_incoming_mqtt_message(topic, payload)
    if result and not result.startswith("skip:"):
        logger.debug("IoT: topic=%r → %s", topic, result)
