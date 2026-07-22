"""Durable MQTT outbox adapter."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone

from ..models import (
    CommandStatus,
    DeviceCommand,
    DeviceOTAJob,
    MQTTOutboxMessage,
    OTAJobStatus,
    OutboxStatus,
)


def enqueue_mqtt(
    *,
    topic: str,
    payload: str,
    qos: int = 1,
    retain: bool = False,
    event_type: str = "",
    reference_id: UUID | None = None,
) -> MQTTOutboxMessage:
    if reference_id:
        message, _ = MQTTOutboxMessage.objects.get_or_create(
            event_type=event_type,
            reference_id=reference_id,
            defaults={
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            },
        )
    else:
        message = MQTTOutboxMessage.objects.create(
            topic=topic,
            payload=payload,
            qos=qos,
            retain=retain,
            event_type=event_type,
        )
    return message


def _claim_next() -> MQTTOutboxMessage | None:
    now = timezone.now()
    with transaction.atomic():
        message = (
            MQTTOutboxMessage.objects.select_for_update()
            .filter(status__in=(OutboxStatus.PENDING, OutboxStatus.FAILED), available_at__lte=now)
            .order_by("created_at")
            .first()
        )
        if not message:
            return None
        message.status = OutboxStatus.PROCESSING
        message.locked_at = now
        message.attempts += 1
        message.save(update_fields=("status", "locked_at", "attempts"))
        return message


def _apply_delivery_result(message: MQTTOutboxMessage) -> None:
    now = timezone.now()
    if message.event_type == "command" and message.reference_id:
        DeviceCommand.objects.filter(
            command_id=message.reference_id, status=CommandStatus.PENDING
        ).update(status=CommandStatus.SENT, sent_at=now)
    elif message.event_type == "ota" and message.reference_id:
        DeviceOTAJob.objects.filter(
            job_id=message.reference_id, status=OTAJobStatus.PENDING
        ).update(status=OTAJobStatus.SENT, command_sent_at=now)
    elif message.event_type.startswith("ota-republish-") and message.reference_id:
        DeviceOTAJob.objects.filter(
            job_id=message.reference_id, status=OTAJobStatus.SENT
        ).update(command_sent_at=now)


def dispatch_one() -> bool:
    message = _claim_next()
    if not message:
        return False
    try:
        from apps.mqtt.client import mqtt_client

        async_to_sync(mqtt_client.publish)(
            message.topic, message.payload, qos=message.qos, retain=message.retain
        )
    except Exception as exc:
        message.status = OutboxStatus.FAILED
        message.last_error = str(exc)[:4000]
        message.locked_at = None
        message.available_at = timezone.now() + timedelta(
            seconds=min(300, 2 ** min(message.attempts, 8))
        )
        message.save(
            update_fields=("status", "last_error", "locked_at", "available_at")
        )
        return True

    with transaction.atomic():
        message.status = OutboxStatus.SENT
        message.sent_at = timezone.now()
        message.locked_at = None
        message.last_error = ""
        message.save(update_fields=("status", "sent_at", "locked_at", "last_error"))
        _apply_delivery_result(message)
    return True


def recover_stale(*, older_than: timedelta = timedelta(minutes=5)) -> int:
    return MQTTOutboxMessage.objects.filter(
        status=OutboxStatus.PROCESSING,
        locked_at__lt=timezone.now() - older_than,
    ).update(status=OutboxStatus.FAILED, locked_at=None, available_at=timezone.now())
