"""
Over-the-air (OTA) jobs: create job, sign download URL, publish downlink, apply status uplink.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import quote

from asgiref.sync import async_to_sync
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.utils import timezone

from . import constants
from .models import (
    Device,
    DeviceOTAJob,
    FirmwareVersion,
    OTAJobStatus,
    Organization,
)

logger = logging.getLogger(__name__)


# Backward compatibility alias
FirmwarePackage = FirmwareVersion


def get_ota_public_base_url() -> str:
    base = (getattr(settings, "IOT_OTA_PUBLIC_BASE", None) or "").strip()
    if base:
        return base.rstrip("/")
    try:
        from django.contrib.sites.models import Site

        s = Site.objects.get_current()
        if s and s.domain:
            scheme = "https" if not settings.DEBUG else "http"
            return f"{scheme}://{s.domain.rstrip('/').split(':')[0]}"
    except Exception:
        pass
    if getattr(settings, "DEBUG", False):
        return "http://127.0.0.1:8000"
    return "https://example.com"


def _cancel_superseded_jobs(device: Device, keep: DeviceOTAJob) -> int:
    """Mark older in-flight jobs cancelled when a new job is created."""
    qs = (
        DeviceOTAJob.objects.filter(device=device)
        .exclude(pk=keep.pk)
        .filter(
            status__in=(
                OTAJobStatus.PENDING,
                OTAJobStatus.SENT,
                OTAJobStatus.IN_PROGRESS,
            )
        )
    )
    count = qs.count()
    now = timezone.now()
    msg = f"Superseded by job {keep.job_id}."
    for old in qs:
        old.status = OTAJobStatus.CANCELLED
        old.error_message = msg
        old.completed_at = now
        old.save(update_fields=["status", "error_message", "completed_at", "id"])
    return count


def get_compatible_firmware_for_device(
    device: Device,
    only_active: bool = True,
    include_mandatory_only: bool = False,
) -> QuerySet:
    """
    Get firmware versions compatible with a device.
    
    Filters by:
    - product match
    - is_active (if only_active=True)
    - hardware version constraints
    - mandatory flag (if include_mandatory_only=True)
    """
    dev_product = (device.firmware_product or "").strip() or "default"
    hw_version = (device.hardware_version or "").strip()

    qs = FirmwareVersion.objects.filter(product=dev_product)
    
    if only_active:
        qs = qs.filter(is_active=True)
    
    if include_mandatory_only:
        qs = qs.filter(is_mandatory=True)

    # Filter by hardware version if device has hardware version set
    if hw_version:
        from django.db.models import Q
        qs = qs.filter(
            Q(min_hardware_version="") | Q(min_hardware_version__lte=hw_version)
        ).filter(
            Q(max_hardware_version="") | Q(max_hardware_version__gte=hw_version)
        )

    return qs.order_by("-created_at")


def create_ota_job(device: Device, firmware: FirmwareVersion) -> DeviceOTAJob:
    if not device.is_active:
        raise ValidationError("Device is not active.")
    if not firmware.is_active or not firmware.file or not firmware.sha256:
        raise ValidationError("Firmware is not available (inactive or not hashed).")
    
    # Validate product compatibility
    dev_product = (device.firmware_product or "").strip() or "default"
    if (firmware.product or "").strip() != dev_product:
        raise ValidationError(
            f"Firmware product {firmware.product!r} does not match device "
            f"firmware_product {dev_product!r}."
        )
    
    # Validate hardware version compatibility
    hw_version = (device.hardware_version or "").strip()
    if hw_version:
        if firmware.min_hardware_version and hw_version < firmware.min_hardware_version:
            raise ValidationError(
                f"Device hardware version {hw_version!r} is below minimum "
                f"required {firmware.min_hardware_version!r} for this firmware."
            )
        if firmware.max_hardware_version and hw_version > firmware.max_hardware_version:
            raise ValidationError(
                f"Device hardware version {hw_version!r} exceeds maximum "
                f"supported {firmware.max_hardware_version!r} for this firmware."
            )
    
    # Check if file actually exists in storage
    from . import firmware_services
    if not firmware_services.validate_file_exists(firmware):
        raise ValidationError(
            f"Firmware file not found in storage. Path: {firmware.storage_path}"
        )
    job = DeviceOTAJob.objects.create(
        device=device,
        firmware=firmware,
        status=OTAJobStatus.PENDING,
    )
    _cancel_superseded_jobs(device, job)
    return job


def build_ota_command_json(job: DeviceOTAJob, download_url: str) -> dict[str, Any]:
    from datetime import UTC

    d = job.device
    o: Organization = d.organization
    fw = job.firmware
    n = timezone.now()
    if timezone.is_naive(n):
        n = timezone.make_aware(n, UTC)
    n = n.astimezone(UTC)
    ts = n.isoformat().replace("+00:00", "Z")
    return {
        "v": constants.ENVELOPE_VERSION,
        "msg_id": str(uuid.uuid4()),
        "ts": ts,
        "org": o.slug,
        "device_id": str(d.device_id),
        "channel": constants.OTA_CHANNEL,
        "schema": constants.OTA_SCHEMA_COMMAND,
        "data": {
            "job_id": str(job.job_id),
            "product": fw.product,
            "version": fw.version,
            "sha256": fw.sha256,
            "size": fw.file_size,
            "url": download_url,
        },
    }


def _publish_ota_payload(job: DeviceOTAJob, public_base: str | None) -> str:
    """Build signed URL, publish to MQTT; return topic (for logging). Does not save job."""
    from apps.mqtt.client import mqtt_client

    base = (public_base or get_ota_public_base_url()).rstrip("/")
    token = signing.dumps(
        {
            "jid": str(job.job_id),
            "d": str(job.device.device_id),
        },
        salt=constants.OTA_DOWNLOAD_SALT,
    )
    download_url = f"{base}/ota/firmware/?t={quote(token, safe='')}"
    d = job.device
    o = d.organization
    topic = f"{constants.IOT_MQTT_TOPIC_PREFIX}/{o.slug}/{d.device_id}/down/ota"
    payload = json.dumps(
        build_ota_command_json(job, download_url),
        ensure_ascii=False,
    )
    try:
        async_to_sync(mqtt_client.publish)(topic, payload, qos=1, retain=False)
    except Exception as e:
        logger.exception("OTA MQTT publish failed job=%s", job.job_id)
        raise ValidationError(
            f"MQTT publish failed (is the bridge connected?). {e}"
        ) from e
    return topic


def publish_ota_command(job: DeviceOTAJob, public_base: str | None = None) -> None:
    if job.status != OTAJobStatus.PENDING:
        raise ValidationError("Only a pending job can be published to MQTT.")
    topic = _publish_ota_payload(job, public_base)
    job.status = OTAJobStatus.SENT
    job.command_sent_at = timezone.now()
    job.save(update_fields=["status", "command_sent_at", "id"])
    logger.info("OTA command published: job=%s topic=%s", job.job_id, topic)


def republish_ota_command(job: DeviceOTAJob, public_base: str | None = None) -> None:
    """
    Send the same OTA command again (new signed URL) for a job already in SENT.
    Use when the device missed the first downlink or the token expired before download.
    """
    if job.status != OTAJobStatus.SENT:
        raise ValidationError("Only a sent job can be republished.")
    topic = _publish_ota_payload(job, public_base)
    job.command_sent_at = timezone.now()
    job.save(update_fields=["command_sent_at", "id"])
    logger.info("OTA command republished: job=%s topic=%s", job.job_id, topic)


def apply_ota_status_uplink(device: Device, envelope: dict[str, Any]) -> None:
    """Update DeviceOTAJob from ota_status.v1 uplink."""
    data = envelope.get("data") or {}
    raw = data.get("job_id")
    if not raw:
        return
    try:
        uid = uuid.UUID(str(raw).strip())
    except (ValueError, TypeError) as e:
        logger.debug("OTA status: bad job_id: %s", e)
        return
    job = (
        DeviceOTAJob.objects.filter(job_id=uid, device=device)
        .select_related("firmware", "device")
        .first()
    )
    if not job:
        return
    if job.status in (
        OTAJobStatus.SUCCESS,
        OTAJobStatus.FAILED,
        OTAJobStatus.CANCELLED,
    ):
        return
    phase = (data.get("phase") or "").lower()
    message = (data.get("message") or "")[:4000]
    if phase in ("success", "complete", "done", "ok", "succeeded"):
        if job.status != OTAJobStatus.CANCELLED:
            job.status = OTAJobStatus.SUCCESS
            job.error_message = ""
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error_message", "completed_at", "id"])
            if job.firmware:
                device.reported_firmware_version = job.firmware.version
                device.save(
                    update_fields=["reported_firmware_version"],
                )
    elif phase in ("failed", "error", "failure"):
        if job.status != OTAJobStatus.CANCELLED:
            job.status = OTAJobStatus.FAILED
            job.error_message = message
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error_message", "completed_at", "id"])
    else:
        if job.status in (OTAJobStatus.PENDING, OTAJobStatus.SENT, OTAJobStatus.IN_PROGRESS):
            job.status = OTAJobStatus.IN_PROGRESS
            if message:
                job.error_message = message
            job.save(
                update_fields=(["status", "error_message", "id"] if message else ["status", "id"])
            )
