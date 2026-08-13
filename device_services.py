"""Provisioning, state-shadow, and command application services."""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from uuid import UUID

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .constants import COMMAND_SCHEMA_REQUEST, ENVELOPE_VERSION, STATE_SCHEMA_DESIRED, build_device_topic, get_iot_app_id
from .models import (
    CommandStatus,
    CredentialStatus,
    Device,
    DeviceCommand,
    DeviceCredential,
    DeviceEvent,
    DeviceProfile,
    DeviceState,
    Organization,
    ProvisioningToken,
)
from .signals import device_command_changed, device_state_changed


def create_provisioning_token(
    organization: Organization,
    profile: DeviceProfile | None,
    *,
    label: str = "",
    ttl: timedelta = timedelta(hours=24),
    max_claims: int = 1,
) -> tuple[ProvisioningToken, str]:
    if profile and profile.organization_id != organization.pk:
        raise ValidationError("Profile must belong to organization.")
    if max_claims < 1 or ttl <= timedelta(0):
        raise ValidationError("Provisioning token requires positive ttl and max_claims.")
    secret = secrets.token_urlsafe(32)
    token = ProvisioningToken(
        organization=organization,
        profile=profile,
        secret_hash=make_password(secret),
        label=label,
        expires_at=timezone.now() + ttl,
        max_claims=max_claims,
    )
    token.full_clean()
    token.save()
    return token, f"{token.token_id}.{secret}"


def _parse_bootstrap_token(raw_token: str):
    try:
        token_id, secret = raw_token.split(".", 1)
        return UUID(token_id), secret
    except (AttributeError, ValueError) as exc:
        raise ValidationError("Invalid provisioning token.") from exc


@transaction.atomic
def claim_device(raw_token: str, *, name: str, hardware_version: str = "") -> tuple[Device, str]:
    token_id, secret = _parse_bootstrap_token(raw_token)
    try:
        token = ProvisioningToken.objects.select_for_update().select_related("organization", "profile").get(token_id=token_id)
    except ProvisioningToken.DoesNotExist as exc:
        raise ValidationError("Invalid provisioning token.") from exc
    if not token.can_claim or not check_password(secret, token.secret_hash):
        raise ValidationError("Provisioning token expired, exhausted, or invalid.")
    if not token.profile_id:
        raise ValidationError("This token requires the auto-registry flow.")

    device = Device(
        organization=token.organization,
        profile=token.profile,
        name=name.strip() or f"Device {token.claim_count + 1}",
        firmware_product=token.profile.product_code or "default",
        hardware_version=hardware_version,
        claimed_at=timezone.now(),
    )
    device.full_clean()
    device.save()
    credential_secret = secrets.token_urlsafe(48)
    credential = DeviceCredential.objects.create(device=device, secret_hash=make_password(credential_secret))
    token.claim_count += 1
    if token.claim_count >= token.max_claims:
        token.is_active = False
    token.save(update_fields=("claim_count", "is_active"))
    DeviceState.objects.create(device=device)
    DeviceEvent.objects.create(
        organization=device.organization, device=device, event_type="device.claimed", data={"profile": token.profile.slug}
    )
    return device, f"{credential.credential_id}.{credential_secret}"


def authenticate_device(raw_credential: str) -> Device | None:
    try:
        credential_id, secret = raw_credential.split(".", 1)
        credential = DeviceCredential.objects.select_related("device", "device__organization").get(
            credential_id=UUID(credential_id), status=CredentialStatus.ACTIVE
        )
    except (AttributeError, ValueError, DeviceCredential.DoesNotExist):
        return None
    if not check_password(secret, credential.secret_hash):
        return None
    credential.last_used_at = timezone.now()
    credential.save(update_fields=("last_used_at",))
    return credential.device if credential.device.is_active and credential.device.organization.is_active else None


def revoke_credential(credential: DeviceCredential):
    credential.status = CredentialStatus.REVOKED
    credential.revoked_at = timezone.now()
    credential.save(update_fields=("status", "revoked_at"))


@transaction.atomic
def set_desired_state(device: Device, desired: dict, *, publish: bool = True) -> DeviceState:
    if not isinstance(desired, dict):
        raise ValidationError("Desired state must be an object.")
    if not device.is_active or not device.organization.is_active:
        raise ValidationError("Device or organization is inactive.")
    state, _ = DeviceState.objects.get_or_create(device=device)
    state = DeviceState.objects.select_for_update().get(pk=state.pk)
    state.desired = desired
    state.desired_version += 1
    state.desired_updated_at = timezone.now()
    state.save(update_fields=("desired", "desired_version", "desired_updated_at"))
    if publish:
        topic = build_device_topic(device, "down", "state")
        body = json.dumps({"v": ENVELOPE_VERSION, "ts": timezone.now().isoformat(), "app_id": get_iot_app_id(), "org": device.organization.slug, "device_id": str(device.device_id), "channel": "state", "schema": STATE_SCHEMA_DESIRED, "data": {"version": state.desired_version, "desired": desired}})
        from .integrations.mqtt import enqueue_mqtt

        enqueue_mqtt(topic=topic, payload=body, qos=1, retain=True, event_type="state")
    transaction.on_commit(
        lambda: device_state_changed.send(sender=DeviceState, device=device, state=state)
    )
    return state


@transaction.atomic
def apply_reported_state(device: Device, envelope: dict) -> DeviceState:
    data = envelope.get("data", {})
    reported = data.get("reported", data)
    if not isinstance(reported, dict):
        raise ValidationError("Reported state must be an object.")
    state, _ = DeviceState.objects.get_or_create(device=device)
    state = DeviceState.objects.select_for_update().get(pk=state.pk)
    state.reported = reported
    try:
        device_version = int(data.get("version", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Reported state version must be an integer.") from exc
    if device_version < 0:
        raise ValidationError("Reported state version cannot be negative.")
    if device_version > 9223372036854775807:
        raise ValidationError("Reported state version is too large.")
    state.reported_version = max(state.reported_version + 1, device_version)
    state.reported_updated_at = timezone.now()
    state.save(update_fields=("reported", "reported_version", "reported_updated_at"))
    transaction.on_commit(
        lambda: device_state_changed.send(sender=DeviceState, device=device, state=state)
    )
    return state


def create_command(device: Device, name: str, payload: dict | None = None, *, timeout_seconds: int = 60) -> DeviceCommand:
    if not device.is_active or not device.organization.is_active:
        raise ValidationError("Device or organization is inactive.")
    if not name.strip() or timeout_seconds < 1:
        raise ValidationError("Command name and positive timeout are required.")
    if payload is not None and not isinstance(payload, dict):
        raise ValidationError("Command payload must be an object.")
    return DeviceCommand.objects.create(
        device=device, name=name.strip(), payload=payload or {}, expires_at=timezone.now() + timedelta(seconds=timeout_seconds)
    )


def publish_command(command: DeviceCommand) -> DeviceCommand:
    if command.status != CommandStatus.PENDING:
        raise ValidationError("Only pending commands can be published.")
    topic = build_device_topic(command.device, "down", "command")
    body = json.dumps({"v": ENVELOPE_VERSION, "ts": timezone.now().isoformat(), "app_id": get_iot_app_id(), "org": command.device.organization.slug, "device_id": str(command.device.device_id), "channel": "command", "schema": COMMAND_SCHEMA_REQUEST, "msg_id": str(command.command_id), "data": {"command_id": str(command.command_id), "name": command.name, "payload": command.payload, "expires_at": command.expires_at.isoformat() if command.expires_at else None}})
    from .integrations.mqtt import enqueue_mqtt

    enqueue_mqtt(
        topic=topic,
        payload=body,
        qos=1,
        event_type="command",
        reference_id=command.command_id,
    )
    return command


@transaction.atomic
def apply_command_status(device: Device, envelope: dict) -> DeviceCommand:
    data = envelope.get("data", {})
    try:
        command = DeviceCommand.objects.select_for_update().get(
            device=device, command_id=UUID(str(data.get("command_id")))
        )
    except (ValueError, DeviceCommand.DoesNotExist) as exc:
        raise ValidationError("Unknown command_id.") from exc
    status = str(data.get("status", "")).lower()
    allowed = {CommandStatus.ACKNOWLEDGED, CommandStatus.SUCCEEDED, CommandStatus.FAILED}
    if status not in allowed:
        raise ValidationError("Invalid command status.")
    transitions = {
        CommandStatus.SENT: allowed,
        CommandStatus.ACKNOWLEDGED: {CommandStatus.SUCCEEDED, CommandStatus.FAILED},
    }
    if status not in transitions.get(command.status, set()):
        raise ValidationError(
            f"Invalid command transition: {command.status} -> {status}."
        )
    command.status = status
    command.result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
    command.error_message = str(data.get("error", ""))
    if status in {CommandStatus.SUCCEEDED, CommandStatus.FAILED}:
        command.completed_at = timezone.now()
    command.save(update_fields=("status", "result", "error_message", "completed_at"))
    transaction.on_commit(
        lambda: device_command_changed.send(
            sender=DeviceCommand, device=device, command=command
        )
    )
    return command
