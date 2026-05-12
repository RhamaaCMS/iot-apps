"""
Protocol parsing, validation, and MQTT ingest. Import from other apps as:

    from apps.IoT import services
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional, cast
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.utils import dateparse, timezone

from .constants import (
    ALLOWED_SCHEMAS,
    ENVELOPE_VERSION,
    IOT_MQTT_TOPIC_PREFIX,
    ONLINE_THRESHOLD_MINUTES,
    OTA_SCHEMA_STATUS,
    ProtocolSpec,
)
from .signals import device_uplink_ingested

logger = logging.getLogger(__name__)


class EnvelopeError(Exception):
    """Client-facing validation error."""


def device_is_online(d) -> bool:
    if not d.last_seen_at:
        return False
    from datetime import timedelta

    return d.last_seen_at >= timezone.now() - timedelta(
        minutes=ONLINE_THRESHOLD_MINUTES
    )


def build_topic_uplink_telemetry(org_slug: str, device_id: str) -> str:
    return f"{IOT_MQTT_TOPIC_PREFIX}/{org_slug}/{device_id}/up/telemetry"


def device_mqtt_message_topic_prefix(d) -> str:
    """
    `topic` prefix to match `MQTTMessage` rows in apps.mqtt for this device
    (default: iot/v1/{org_slug}/{device_id}/, or custom `device.topic_prefix`).
    """
    t = (getattr(d, "topic_prefix", None) or "").strip()
    if t:
        return t.rstrip("/") + "/"
    return f"{IOT_MQTT_TOPIC_PREFIX}/{d.organization.slug}/{d.device_id}/"


def recent_mqtt_messages_for_device(d, *, limit: int = 50) -> tuple[str, list[dict[str, Any]]]:
    """Load persisted MQTT in/out for admin UI. Returns (prefix, rows)."""
    from apps.mqtt.models import MQTTMessage

    prefix = device_mqtt_message_topic_prefix(d)
    limit = min(max(1, int(limit)), 200)
    qs = (
        MQTTMessage.objects.filter(topic__startswith=prefix)
        .order_by("-received_at")[:limit]
    )
    messages: list[dict[str, Any]] = []
    for m in qs:
        messages.append(
            {
                "direction": m.direction,
                "topic": m.topic,
                "payload": m.payload,
                "qos": m.qos,
                "received_at": m.received_at.isoformat(),
            }
        )
    return prefix, messages


def parse_iot_uplink_topic(topic: str) -> dict[str, str] | None:
    """
    Uplink: {IOT_MQTT_TOPIC_PREFIX}/{org_slug}/{device_id}/up[/...]
    """
    pfx = [p for p in IOT_MQTT_TOPIC_PREFIX.strip("/").split("/") if p]
    parts = [p for p in topic.split("/") if p]
    if len(parts) < len(pfx) + 3:
        return None
    for i, seg in enumerate(pfx):
        if parts[i] != seg:
            return None
    j = len(pfx)
    if parts[j + 2] != "up":
        return None
    return {
        "org_slug": parts[j],
        "device_id": parts[j + 1],
        "raw_topic": topic,
    }


def parse_envelope_dict(raw: dict[str, Any]) -> dict[str, Any]:
    for k in ProtocolSpec.REQUIRED_ENVELOPE_KEYS:
        if k not in raw:
            raise EnvelopeError(f"Missing envelope key: {k}")
    if raw.get("v") != ENVELOPE_VERSION:
        raise EnvelopeError(
            f"Unsupported envelope v={raw.get('v')!r}; need {ENVELOPE_VERSION}"
        )
    for k in ("org", "device_id", "channel", "schema"):
        if not isinstance(raw.get(k), str) or not str(raw.get(k, "")).strip():
            raise EnvelopeError(f"Invalid or empty string field: {k}")
    if not isinstance(raw.get("data"), dict):
        raise EnvelopeError('Field "data" must be a JSON object')
    if "msg_id" in raw and raw["msg_id"] is not None:
        if not isinstance(raw.get("msg_id"), str):
            raise EnvelopeError("msg_id must be a string when present")
    if ALLOWED_SCHEMAS and str(raw.get("schema")) not in ALLOWED_SCHEMAS:
        raise EnvelopeError(
            f"Unknown schema: {raw.get('schema')!r}; allowed: {sorted(ALLOWED_SCHEMAS)}"
        )
    ts = raw.get("ts")
    if not isinstance(ts, str):
        raise EnvelopeError("ts must be a string (ISO-8601)")
    parsed: datetime | None = dateparse.parse_datetime(ts)
    if parsed is None and isinstance(ts, str) and "T" in ts and ts.endswith("Z"):
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, OSError) as e:
            raise EnvelopeError("Invalid ts datetime") from e
    if parsed is None:
        raise EnvelopeError("Invalid ts datetime")
    if timezone.is_naive(parsed):
        from datetime import UTC

        parsed = parsed.replace(tzinfo=UTC)
    return cast(dict[str, Any], {**raw, "_parsed_ts": parsed})


def parse_envelope_string(payload: str) -> dict[str, Any]:
    if not (payload and payload.strip()):
        raise EnvelopeError("Empty payload")
    try:
        d = json.loads(payload)
    except json.JSONDecodeError as e:
        raise EnvelopeError("Payload is not valid JSON") from e
    if not isinstance(d, dict):
        raise EnvelopeError("JSON root must be an object")
    return parse_envelope_dict(d)


def validate_envelope(
    raw_text: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    try:
        return parse_envelope_string(raw_text), None
    except EnvelopeError as e:
        return None, str(e)
    except Exception as e:  # pragma: no cover
        logger.exception("validate_envelope")
        return None, str(e)


def _get_device_by_uuid(s: str):
    from .models import Device

    try:
        u = UUID(s.strip(), version=None)
    except (ValueError, TypeError) as e:
        raise EnvelopeError("device_id is not a valid UUID") from e
    try:
        return Device.objects.select_related("organization").get(device_id=u)
    except ObjectDoesNotExist as e:
        raise EnvelopeError("Unknown device_id") from e


def process_incoming_mqtt_message(topic: str, payload: str) -> str:
    tnorm = (topic or "").strip()
    if not tnorm.startswith(f"{IOT_MQTT_TOPIC_PREFIX}/"):
        return "skip: not iot/v1"
    tinfo = parse_iot_uplink_topic(tnorm)
    if not tinfo:
        return "error: topic pattern (expected iot/v1/{org}/{device_id}/up/...)"
    env, err = validate_envelope(payload)
    if err or not env:
        return f"error: {err}"
    if (
        tinfo["org_slug"] != env["org"].strip()
        or tinfo["device_id"] != env["device_id"].strip()
    ):
        return "error: topic and envelope org/device mismatch"

    if env.get("channel", "").lower() in ("ack", "nack"):
        return "skip: ack channel"

    try:
        d = _get_device_by_uuid(env["device_id"])
    except EnvelopeError as e:
        return f"error: {e}"
    if not d.is_active or not d.organization.is_active:
        return "error: device or org disabled"
    if env["org"].strip() != d.organization.slug or str(d.device_id) != env["device_id"].strip():
        return "error: org or device_id mismatch"
    if tinfo["org_slug"] != d.organization.slug or tinfo["device_id"] != str(d.device_id):
        return "error: topic vs database mismatch"

    ch = env.get("channel", "").lower()
    if ch == "ota" and str(env.get("schema") or "") == OTA_SCHEMA_STATUS:
        from . import ota_services

        ota_services.apply_ota_status_uplink(d, env)

    p_ts = cast(datetime | None, env.get("_parsed_ts"))
    d.last_seen_at = p_ts or timezone.now()
    d.last_channel = env.get("channel", "")[:100]
    d.last_schema = env.get("schema", "")[:200]
    d.save(update_fields=["last_seen_at", "last_channel", "last_schema"])
    device_uplink_ingested.send(
        sender=d.__class__, device=d, envelope=env, topic=tnorm
    )
    return "ok"