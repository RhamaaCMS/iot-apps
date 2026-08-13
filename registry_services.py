"""Secure, operator-approved device self-registration."""

from __future__ import annotations

import json
import re
from uuid import UUID

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .device_services import _parse_bootstrap_token
from .models import (
    Device,
    DeviceCredential,
    DeviceEvent,
    DeviceProfile,
    DeviceRegistrationRequest,
    DeviceState,
    ProvisioningToken,
    RegistrationStatus,
)


def infer_data_shape(value, *, depth: int = 0):
    if depth > 8:
        raise ValidationError("Sample data nesting is too deep.")
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        shapes = {json.dumps(infer_data_shape(item, depth=depth + 1), sort_keys=True) for item in value[:32]}
        if not shapes:
            return ["unknown"]
        if len(shapes) == 1:
            return [json.loads(next(iter(shapes)))]
        return ["mixed"]
    if isinstance(value, dict):
        if len(value) > 128:
            raise ValidationError("Sample data has too many fields.")
        return {str(key): infer_data_shape(value[key], depth=depth + 1) for key in sorted(value)}
    raise ValidationError("Sample data contains an unsupported value type.")


def normalize_esp32_mac(value: str) -> str:
    mac = re.sub(r"[^0-9A-Fa-f]", "", str(value)).upper()
    if not re.fullmatch(r"[0-9A-F]{12}", mac):
        raise ValidationError("hardware_id must be a valid 48-bit ESP32 MAC address.")
    if mac == "000000000000" or mac == "FFFFFFFFFFFF":
        raise ValidationError("hardware_id is not a usable ESP32 MAC address.")
    return mac


def find_matching_profile(organization, schema: str, shape: dict, product: str = ""):
    for profile in DeviceProfile.objects.filter(organization=organization, is_active=True).order_by("name"):
        if product and profile.product_code and profile.product_code != product:
            continue
        if profile.schema_contracts.get(schema) == shape:
            return profile
    return None


@transaction.atomic
def request_registration(*, raw_token: str, credential_secret: str, manifest: dict):
    if len(credential_secret) < 24:
        raise ValidationError("Credential secret is too short.")
    token_id, token_secret = _parse_bootstrap_token(raw_token)
    try:
        token = ProvisioningToken.objects.select_for_update().select_related("organization", "profile").get(token_id=token_id)
    except ProvisioningToken.DoesNotExist as exc:
        raise ValidationError("Invalid registry token.") from exc
    if not check_password(token_secret, token.secret_hash):
        raise ValidationError("Registry token expired, exhausted, or invalid.")

    hardware_id = normalize_esp32_mac(manifest.get("hardware_id", ""))
    schema = str(manifest.get("schema", "")).strip()[:200]
    sample_data = manifest.get("sample_data")
    if not hardware_id or not schema or not isinstance(sample_data, dict):
        raise ValidationError("hardware_id, schema, and object sample_data are required.")
    shape = infer_data_shape(sample_data)

    existing = DeviceRegistrationRequest.objects.filter(
        provisioning_token=token, hardware_id=hardware_id
    ).first()
    if existing:
        if not check_password(credential_secret, existing.secret_hash):
            raise ValidationError("Registration identity conflict.")
        return existing, False
    if not token.can_claim:
        raise ValidationError("Registry token expired, exhausted, or invalid.")
    if Device.objects.filter(device_id=hardware_id).exists():
        raise ValidationError("This ESP32 MAC is already registered.")

    product = str(manifest.get("firmware_product", "")).strip()[:100]
    suggested = token.profile or find_matching_profile(token.organization, schema, shape, product)
    request = DeviceRegistrationRequest.objects.create(
        provisioning_token=token,
        organization=token.organization,
        suggested_profile=suggested,
        secret_hash=make_password(credential_secret),
        hardware_id=hardware_id,
        requested_name=(str(manifest.get("name", "")).strip() or f"ESP32 {hardware_id[-6:]}")[:255],
        hardware_version=str(manifest.get("hardware_version", "")).strip()[:32],
        firmware_product=product,
        firmware_version=str(manifest.get("firmware_version", "")).strip()[:100],
        schema=schema,
        sample_data=sample_data,
        data_shape=shape,
    )
    return request, True


def authenticate_registration(request_id: str, credential_secret: str):
    try:
        request = DeviceRegistrationRequest.objects.select_related(
            "device", "device__organization", "suggested_profile"
        ).get(request_id=UUID(request_id))
    except (ValueError, DeviceRegistrationRequest.DoesNotExist):
        return None
    return request if check_password(credential_secret, request.secret_hash) else None


def _unique_profile_slug(organization, name: str) -> str:
    base = (slugify(name) or "auto-profile")[:80]
    candidate = base
    number = 1
    while DeviceProfile.objects.filter(organization=organization, slug=candidate).exists():
        number += 1
        candidate = f"{base[:75]}-{number}"
    return candidate


@transaction.atomic
def approve_registration(request: DeviceRegistrationRequest, *, profile_name: str = ""):
    request = DeviceRegistrationRequest.objects.select_for_update().select_related(
        "provisioning_token", "organization", "suggested_profile"
    ).get(pk=request.pk)
    if request.status != RegistrationStatus.PENDING:
        raise ValidationError("Only pending registration can be approved.")
    token = ProvisioningToken.objects.select_for_update().get(pk=request.provisioning_token_id)
    if not token.can_claim:
        raise ValidationError("Registry token is no longer valid.")

    profile = request.suggested_profile
    if not profile or not profile.is_active:
        name = (profile_name.strip() or request.firmware_product or request.schema.split(".", 1)[0] or "Auto profile")[:255]
        profile = DeviceProfile(
            organization=request.organization,
            name=name,
            slug=_unique_profile_slug(request.organization, name),
            product_code=request.firmware_product,
            allowed_schemas=[request.schema],
            schema_contracts={request.schema: request.data_shape},
        )
        profile.full_clean()
        profile.save()

    device = Device(
        organization=request.organization,
        profile=profile,
        name=request.requested_name,
        device_id=request.hardware_id,
        firmware_product=profile.product_code or profile.slug,
        hardware_version=request.hardware_version,
        reported_firmware_version=request.firmware_version,
        claimed_at=timezone.now(),
    )
    device.full_clean()
    device.save()
    DeviceCredential.objects.create(
        device=device,
        credential_id=request.credential_id,
        secret_hash=request.secret_hash,
    )
    DeviceState.objects.create(device=device)
    token.claim_count += 1
    if token.claim_count >= token.max_claims:
        token.is_active = False
    token.save(update_fields=("claim_count", "is_active"))
    request.suggested_profile = profile
    request.device = device
    request.status = RegistrationStatus.APPROVED
    request.reviewed_at = timezone.now()
    request.save(update_fields=("suggested_profile", "device", "status", "reviewed_at"))
    DeviceEvent.objects.create(
        organization=request.organization,
        device=device,
        event_type="device.registry_approved",
        data={"request_id": str(request.request_id), "profile": profile.slug},
    )
    return device


@transaction.atomic
def auto_register_device(*, raw_token: str, credential_secret: str, manifest: dict):
    """Idempotent one-call registration: infer/reuse profile and activate device."""
    registration, created = request_registration(
        raw_token=raw_token,
        credential_secret=credential_secret,
        manifest=manifest,
    )
    if registration.status == RegistrationStatus.REJECTED:
        raise ValidationError("Registration was rejected.")
    if registration.status == RegistrationStatus.PENDING:
        approve_registration(registration)
        registration.refresh_from_db()
    if not registration.device_id:
        raise ValidationError("Registration did not create a device.")
    return registration, created


def reject_registration(request: DeviceRegistrationRequest, reason: str = ""):
    if request.status != RegistrationStatus.PENDING:
        raise ValidationError("Only pending registration can be rejected.")
    request.status = RegistrationStatus.REJECTED
    request.rejection_reason = reason.strip()[:4000]
    request.reviewed_at = timezone.now()
    request.save(update_fields=("status", "rejection_reason", "reviewed_at"))
    return request
