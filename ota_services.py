"""
Over-the-air (OTA) jobs: create job, sign download URL, publish downlink, apply status uplink.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
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
    now = timezone.now()
    msg = f"Superseded by job {keep.job_id}."
    return qs.update(
        status=OTAJobStatus.CANCELLED,
        error_message=msg,
        completed_at=now,
    )


def get_compatible_firmware_for_device(
    device: Device,
    only_active: bool = True,
    include_mandatory_only: bool = False,
) -> QuerySet:
    """
    Get firmware versions compatible with a device.
    
    Filters by:
    - exact device profile ownership
    - is_active (if only_active=True)
    - hardware version constraints
    - mandatory flag (if include_mandatory_only=True)
    """
    hw_version = (device.hardware_version or "").strip()

    qs = FirmwareVersion.objects.none()
    if device.profile_id:
        qs = FirmwareVersion.objects.filter(profile_id=device.profile_id)
    
    if only_active:
        qs = qs.filter(is_active=True)
    
    if include_mandatory_only:
        qs = qs.filter(is_mandatory=True)

    # Filter by hardware version if device has hardware version set
    if hw_version:
        from .versioning import version_in_range

        compatible_ids = [
            firmware.pk
            for firmware in qs.only(
                "pk", "min_hardware_version", "max_hardware_version"
            )
            if version_in_range(
                hw_version,
                firmware.min_hardware_version,
                firmware.max_hardware_version,
            )
        ]
        qs = qs.filter(pk__in=compatible_ids)

    return qs.order_by("-created_at")


@transaction.atomic
def create_ota_job(device: Device, firmware: FirmwareVersion) -> DeviceOTAJob:
    device = Device.objects.select_for_update().get(pk=device.pk)
    if not device.is_active:
        raise ValidationError("Device is not active.")
    if not firmware.is_active or not firmware.file or not firmware.sha256:
        raise ValidationError("Firmware is not available (inactive or not hashed).")
    
    if not device.profile_id:
        raise ValidationError("Device must have a profile before receiving OTA firmware.")
    if not firmware.profile_id or firmware.profile_id != device.profile_id:
        raise ValidationError(
            "Firmware belongs to a different device profile."
        )
    
    # Validate hardware version compatibility
    hw_version = (device.hardware_version or "").strip()
    if hw_version and not firmware.is_compatible_with_device(device):
        raise ValidationError(
            f"Device hardware version {hw_version!r} is incompatible with this firmware."
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
        "app_id": constants.get_iot_app_id(),
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


def _publish_ota_payload(
    job: DeviceOTAJob, public_base: str | None, *, deduplicate: bool
) -> str:
    """Build signed URL and enqueue MQTT outbox message."""

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
    topic = constants.build_device_topic(d, "down", "ota")
    payload = json.dumps(
        build_ota_command_json(job, download_url),
        ensure_ascii=False,
    )
    from .integrations.mqtt import enqueue_mqtt

    enqueue_mqtt(
        topic=topic,
        payload=payload,
        qos=1,
        retain=False,
        event_type="ota" if deduplicate else f"ota-republish-{uuid.uuid4().hex[:8]}",
        reference_id=job.job_id,
    )
    return topic


def publish_ota_command(job: DeviceOTAJob, public_base: str | None = None) -> None:
    if job.status != OTAJobStatus.PENDING:
        raise ValidationError("Only a pending job can be published to MQTT.")
    topic = _publish_ota_payload(job, public_base, deduplicate=True)
    logger.info("OTA command queued: job=%s topic=%s", job.job_id, topic)


def republish_ota_command(job: DeviceOTAJob, public_base: str | None = None) -> None:
    """
    Send the same OTA command again (new signed URL) for a job already in SENT.
    Use when the device missed the first downlink or the token expired before download.
    """
    if job.status != OTAJobStatus.SENT:
        raise ValidationError("Only a sent job can be republished.")
    topic = _publish_ota_payload(job, public_base, deduplicate=False)
    logger.info("OTA command requeued: job=%s topic=%s", job.job_id, topic)


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
