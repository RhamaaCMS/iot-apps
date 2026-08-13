import json
import uuid
from datetime import UTC, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from wagtail.admin.auth import require_admin_access
from django.contrib import messages
from . import ota_services
from . import services
from . import registry_services
from .admin_forms import (
    DeviceForm,
    DeviceProfileForm,
    ExistingUserMembershipForm,
    FirmwareVersionForm,
    IoTUserMembershipForm,
    OrganizationForm,
)
from .admin_snippet_urls import all_snippet_links, snippet_edit_url
from .constants import (
    ALLOWED_SCHEMAS,
    ENVELOPE_VERSION,
    ONLINE_THRESHOLD_MINUTES,
    build_device_topic,
    get_iot_app_id,
    mqtt_topic_root,
)
from .models import (
    Device,
    DeviceCommand,
    DeviceOTAJob,
    DeviceProfile,
    DeviceRegistrationRequest,
    FirmwareVersion,
    Organization,
    OrganizationMembership,
    RegistrationStatus,
    TelemetryRecord,
)
from .access import (
    manageable_organization_ids_for_user,
    scope_devices,
    scope_manageable_devices,
    scope_manageable_ota_jobs,
    scope_memberships,
    scope_organizations,
    scope_ota_jobs,
)

# Backward compatibility alias
FirmwarePackage = FirmwareVersion


def _base_iot_context(active_section: str, user=None) -> dict:
    return {
        "iot_active_section": active_section,
        "iot_app_id": get_iot_app_id(),
        "iot_topic_root": mqtt_topic_root(),
        "snippets": all_snippet_links(user),
    }


@require_admin_access
def dashboard(request):
    org_count = scope_organizations(Organization.objects.filter(is_active=True), request.user).count()
    dev_qs = scope_devices(
        Device.objects.select_related("organization", "profile"), request.user
    )
    now = timezone.now()
    online_cutoff = now - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
    activity_cutoff = now - timedelta(hours=24)
    dev_count = dev_qs.count()
    active_count = dev_qs.filter(is_active=True).count()
    online = dev_qs.filter(
        is_active=True, last_seen_at__gte=online_cutoff
    ).count()
    offline = max(active_count - online, 0)
    online_percentage = round((online / active_count) * 100) if active_count else 0
    telemetry_24h = TelemetryRecord.objects.filter(
        device__in=dev_qs, received_at__gte=activity_cutoff
    ).count()
    pending_commands = DeviceCommand.objects.filter(
        device__in=dev_qs,
        status__in=("pending", "sent", "acknowledged"),
    ).count()
    ota_in_flight = DeviceOTAJob.objects.filter(
        device__in=dev_qs,
        status__in=("pending", "sent", "in_progress"),
    ).count()

    recent_activity = [
        {
            "device_name": item.device.name,
            "org_slug": item.device.organization.slug,
            "channel": item.channel,
            "schema": item.schema,
            "received_at": item.received_at,
        }
        for item in TelemetryRecord.objects.filter(device__in=dev_qs)
        .select_related("device", "device__organization")
        .order_by("-received_at")[:6]
    ]

    devices = []
    preview_n = 8
    for d in dev_qs.order_by("-last_seen_at", "name")[:preview_n]:
        devices.append(
            {
                "pk": d.pk,
                "name": d.name,
                "org_slug": d.organization.slug,
                "device_id": str(d.device_id),
                "last_seen": d.last_seen_at,
                "online": d.is_active and services.device_is_online(d),
                "is_active": d.is_active,
                "last_channel": d.last_channel or "—",
                "last_schema": d.last_schema or "—",
                "firmware_version": d.reported_firmware_version or "—",
                "hardware_version": d.hardware_version or "—",
            }
        )

    return TemplateResponse(
        request,
        "IoT/admin/dashboard.html",
        {
            "title": "IoT",
            "org_count": org_count,
            "device_count": dev_count,
            "active_device_count": active_count,
            "online_count": online,
            "offline_count": offline,
            "online_percentage": online_percentage,
            "telemetry_24h": telemetry_24h,
            "pending_commands": pending_commands,
            "ota_in_flight": ota_in_flight,
            "recent_activity": recent_activity,
            "online_threshold_minutes": ONLINE_THRESHOLD_MINUTES,
            "devices": devices,
            "devices_preview_limit": preview_n,
            "has_more_devices": dev_count > preview_n,
            "envelope_version": ENVELOPE_VERSION,
            "topic_prefix": mqtt_topic_root(),
            "allowed_schemas": list(ALLOWED_SCHEMAS),
            "example_telemetry_topic": f"{mqtt_topic_root()}/kirei/550e8400-e29b-41d4-a716-446655440000/up/telemetry",
            "now_iso": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            **_base_iot_context("summary", request.user),
        },
    )


@require_admin_access
def panel_organizations(request):
    return redirect("iot:panel_memberships")


@require_admin_access
@require_http_methods(["GET", "POST"])
def panel_memberships(request):
    mode = (request.POST.get("membership_mode") or "new") if request.method == "POST" else "new"
    if mode not in {"new", "existing", "organization"}:
        mode = "new"
    new_user_form = IoTUserMembershipForm(
        request.POST if request.method == "POST" and mode == "new" else None,
        prefix="new",
    )
    existing_user_form = ExistingUserMembershipForm(
        request.POST if request.method == "POST" and mode == "existing" else None,
        prefix="existing",
    )
    organization_form = OrganizationForm(
        request.POST if request.method == "POST" and mode == "organization" else None,
        prefix="organization",
    )
    if request.method == "POST":
        if not request.user.is_superuser:
            raise PermissionDenied
        if mode == "new" and new_user_form.is_valid():
            with transaction.atomic():
                user = new_user_form.save()
            messages.success(request, f"User {user.get_username()} dan akses IoT berhasil dibuat.")
            return redirect("iot:panel_memberships")
        if mode == "existing" and existing_user_form.is_valid():
            membership = existing_user_form.save()
            messages.success(
                request,
                f"User {membership.user.get_username()} berhasil ditambahkan ke {membership.organization.name}.",
            )
            return redirect("iot:panel_memberships")
        if mode == "organization" and organization_form.is_valid():
            organization = organization_form.save()
            messages.success(request, f"Organisasi {organization.name} berhasil dibuat.")
            return redirect("iot:panel_memberships")

    organizations = (
        scope_organizations(Organization.objects.all(), request.user)
        .annotate(
            _num_devices=Count("devices", distinct=True),
            _num_members=Count("memberships", distinct=True),
        )
        .order_by("name")
    )
    organization_rows = [
        {
            "pk": organization.pk,
            "name": organization.name,
            "slug": organization.slug,
            "is_active": organization.is_active,
            "num_devices": organization._num_devices,
            "num_members": organization._num_members,
            "edit_href": snippet_edit_url("organization", organization.pk)
            if request.user.is_superuser
            else None,
        }
        for organization in organizations
    ]

    q = scope_memberships(OrganizationMembership.objects.select_related(
        "user", "organization"
    ), request.user).order_by("organization__name", "user__email")
    rows = []
    for m in q:
        rows.append(
            {
                "pk": m.pk,
                "user": m.user.get_username(),
                "email": getattr(m.user, "email", "") or "—",
                "organization": m.organization.name,
                "org_slug": m.organization.slug,
                "role": m.get_role_display(),
                "role_key": m.role,
                "edit_href": snippet_edit_url("organizationmembership", m.pk) if request.user.is_superuser else None,
            }
        )
    return TemplateResponse(
        request,
        "IoT/admin/panel_memberships.html",
        {
            "title": "Pengguna & organisasi — IoT",
            "rows": rows,
            "row_count": len(rows),
            "new_user_form": new_user_form,
            "existing_user_form": existing_user_form,
            "organization_form": organization_form,
            "organization_rows": organization_rows,
            "organization_count": len(organization_rows),
            "active_organization_count": sum(1 for row in organization_rows if row["is_active"]),
            "admin_membership_count": sum(1 for row in rows if row["role_key"] == "admin"),
            "membership_mode": mode,
            "open_membership_modal": request.method == "POST" and mode in {"new", "existing"},
            "open_organization_modal": request.method == "POST" and mode == "organization",
            **_base_iot_context("memberships", request.user),
        },
    )


@require_admin_access
@require_http_methods(["GET", "POST"])
def panel_devices(request):
    form = DeviceForm(request.POST or None)
    if request.method == "POST":
        if not request.user.is_superuser:
            raise PermissionDenied
        if form.is_valid():
            device = form.save()
            messages.success(request, f"Perangkat {device.name} berhasil dibuat.")
            return redirect("iot:panel_devices")

    dev_qs = scope_devices(Device.objects.select_related("organization", "profile"), request.user).order_by(
        "organization__name", "name"
    )
    rows = []
    for d in dev_qs:
        rows.append({
            "pk": d.pk, "name": d.name,
            "org_slug": d.organization.slug, "org_name": d.organization.name,
            "device_id": str(d.device_id),
            "profile": d.profile.name if d.profile_id else "—",
            "firmware_product": d.firmware_product,
            "is_active": d.is_active,
            "online": d.is_active and services.device_is_online(d),
            "last_seen": d.last_seen_at,
            "last_channel": d.last_channel or "—", "last_schema": d.last_schema or "—",
            "edit_href": snippet_edit_url("device", d.pk) if request.user.is_superuser else None,
            "topic_filter_prefix": services.device_mqtt_message_topic_prefix(d),
        })
    return TemplateResponse(request, "IoT/admin/panel_devices.html", {
        "title": "Perangkat — IoT", "rows": rows, "row_count": len(rows),
        "online_count": sum(1 for row in rows if row["online"]),
        "inactive_count": sum(1 for row in rows if not row["is_active"]),
        "profiled_count": sum(1 for row in rows if row["profile"] != "—"),
        "online_threshold_minutes": ONLINE_THRESHOLD_MINUTES,
        "create_form": form, "open_create_modal": request.method == "POST" and form.errors,
        **_base_iot_context("devices", request.user),
    })


@require_admin_access
@require_http_methods(["GET", "POST"])
def panel_registrations(request):
    if request.method == "POST":
        if not request.user.is_superuser:
            raise PermissionDenied
        registration = get_object_or_404(
            DeviceRegistrationRequest.objects.select_related("organization", "suggested_profile"),
            pk=request.POST.get("registration_id"),
        )
        action = request.POST.get("registry_action")
        try:
            if action == "approve":
                device = registry_services.approve_registration(
                    registration, profile_name=request.POST.get("profile_name", "")
                )
                messages.success(request, f"{device.name} terdaftar dan siap terhubung.")
            elif action == "reject":
                registry_services.reject_registration(
                    registration, request.POST.get("reason", "")
                )
                messages.success(request, "Permintaan registrasi ditolak.")
            else:
                raise ValidationError("Aksi registrasi tidak dikenal.")
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        return redirect("iot:panel_registrations")

    allowed_orgs = scope_organizations(Organization.objects.all(), request.user)
    registrations = DeviceRegistrationRequest.objects.filter(
        organization__in=allowed_orgs
    ).select_related("organization", "suggested_profile", "device").order_by(
        "status", "-created_at"
    )[:200]
    rows = [
        {
            "pk": item.pk,
            "request_id": str(item.request_id),
            "name": item.requested_name,
            "hardware_id": item.hardware_id,
            "organization": item.organization.name,
            "org_slug": item.organization.slug,
            "schema": item.schema,
            "product": item.firmware_product or "—",
            "hardware_version": item.hardware_version or "—",
            "firmware_version": item.firmware_version or "—",
            "shape": json.dumps(item.data_shape, ensure_ascii=False, indent=2),
            "suggested_profile": item.suggested_profile,
            "status": item.status,
            "status_label": item.get_status_display(),
            "device": item.device,
            "created_at": item.created_at,
        }
        for item in registrations
    ]
    return TemplateResponse(
        request,
        "IoT/admin/panel_registrations.html",
        {
            "title": "Registrasi perangkat — IoT",
            "rows": rows,
            "pending_count": sum(1 for row in rows if row["status"] == RegistrationStatus.PENDING),
            **_base_iot_context("registrations", request.user),
        },
    )
@require_admin_access
@require_http_methods(["GET", "POST"])
def panel_profiles(request):
    form = DeviceProfileForm(request.POST or None)
    if request.method == "POST":
        if not request.user.is_superuser:
            raise PermissionDenied
        if form.is_valid():
            profile = form.save()
            messages.success(request, f"Device profile {profile.name} berhasil dibuat.")
            return redirect("iot:panel_profiles")

    profiles = DeviceProfile.objects.select_related("organization").annotate(
        _num_devices=Count("devices", distinct=True)
    )
    allowed_org_ids = scope_organizations(
        Organization.objects.all(), request.user
    ).values_list("pk", flat=True)
    profiles = profiles.filter(organization_id__in=allowed_org_ids).order_by(
        "organization__name", "name"
    )
    rows = [
        {
            "pk": profile.pk,
            "name": profile.name,
            "slug": profile.slug,
            "organization": profile.organization.name,
            "org_slug": profile.organization.slug,
            "product_code": profile.product_code or "—",
            "heartbeat": profile.heartbeat_interval_seconds,
            "is_active": profile.is_active,
            "num_devices": profile._num_devices,
            "edit_href": snippet_edit_url("deviceprofile", profile.pk)
            if request.user.is_superuser
            else None,
        }
        for profile in profiles
    ]
    return TemplateResponse(
        request,
        "IoT/admin/panel_profiles.html",
        {
            "title": "Device Profiles — IoT",
            "rows": rows,
            "row_count": len(rows),
            "create_form": form,
            "open_create_modal": request.method == "POST" and form.errors,
            **_base_iot_context("profiles", request.user),
        },
    )


@require_admin_access
@require_http_methods(["GET", "POST"])
def panel_firmware(request):
    form = FirmwareVersionForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not request.user.is_superuser:
            raise PermissionDenied
        if form.is_valid():
            firmware = form.save(commit=False)
            firmware.created_by = request.user
            firmware.save()
            messages.success(request, f"Firmware {firmware} berhasil diunggah.")
            return redirect("iot:panel_firmware")

    firmware_versions = FirmwareVersion.objects.select_related(
        "created_by", "profile", "profile__organization"
    ).order_by("-created_at")[:200]
    rows = [
        {
            "pk": firmware.pk,
            "product": firmware.product,
            "profile": firmware.profile.name if firmware.profile_id else "Legacy / unmapped",
            "profile_slug": firmware.profile.slug if firmware.profile_id else "—",
            "version": firmware.version,
            "file_size": firmware.file_size,
            "sha256": firmware.sha256,
            "is_active": firmware.is_active,
            "is_mandatory": firmware.is_mandatory,
            "created": firmware.created_at,
            "created_by": firmware.created_by,
            "edit_href": snippet_edit_url("firmwareversion", firmware.pk)
            if request.user.is_superuser
            else None,
        }
        for firmware in firmware_versions
    ]
    return TemplateResponse(
        request,
        "IoT/admin/panel_firmware.html",
        {
            "title": "Firmware — IoT",
            "rows": rows,
            "row_count": len(rows),
            "create_form": form,
            "open_create_modal": request.method == "POST" and form.errors,
            **_base_iot_context("firmware", request.user),
        },
    )


@require_admin_access
@require_http_methods(["GET", "POST"])
def panel_ota(request):
    """
    OTA: create jobs (firmware + device) and publish pending jobs to MQTT.
    """
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "create":
            try:
                dev_pk = int(request.POST.get("device_pk") or 0)
                fw_pk = int(request.POST.get("firmware_pk") or 0)
            except (TypeError, ValueError):
                dev_pk, fw_pk = 0, 0
            device = get_object_or_404(
                scope_manageable_devices(Device.objects.select_related("organization"), request.user), pk=dev_pk
            )
            firmware = get_object_or_404(FirmwarePackage, pk=fw_pk)
            try:
                job = ota_services.create_ota_job(device, firmware)
            except ValidationError as e:
                m = e.messages[0] if getattr(e, "messages", None) else str(e)
                messages.error(request, m)
            else:
                messages.success(
                    request,
                    f"Job {job.job_id} created. Publish to send OTA to the device.",
                )
            return redirect("iot:panel_ota")

        if action == "publish":
            raw = (request.POST.get("job_id") or "").strip()
            try:
                ju = uuid.UUID(raw)
            except (TypeError, ValueError):
                messages.error(request, "Invalid job_id.")
                return redirect("iot:panel_ota")
            job = get_object_or_404(
                scope_manageable_ota_jobs(DeviceOTAJob.objects.select_related("device", "firmware", "device__organization"), request.user),
                job_id=ju,
            )
            try:
                ota_services.publish_ota_command(job)
            except ValidationError as e:
                m = e.messages[0] if getattr(e, "messages", None) else str(e)
                messages.error(request, m)
            else:
                messages.success(
                    request,
                    f"OTA command queued for job {job.job_id}.",
                )
            return redirect("iot:panel_ota")

        if action == "republish":
            raw = (request.POST.get("job_id") or "").strip()
            try:
                ju = uuid.UUID(raw)
            except (TypeError, ValueError):
                messages.error(request, "Invalid job_id.")
                return redirect("iot:panel_ota")
            job = get_object_or_404(
                scope_manageable_ota_jobs(DeviceOTAJob.objects.select_related("device", "firmware", "device__organization"), request.user),
                job_id=ju,
            )
            try:
                ota_services.republish_ota_command(job)
            except ValidationError as e:
                m = e.messages[0] if getattr(e, "messages", None) else str(e)
                messages.error(request, m)
            else:
                messages.success(
                    request,
                    f"OTA command requeued for job {job.job_id} (new signed URL).",
                )
            return redirect("iot:panel_ota")

    jobs = (
        scope_ota_jobs(DeviceOTAJob.objects.select_related("device", "device__organization", "firmware"), request.user)
        .order_by("-created_at")[:80]
    )
    manageable_ids = manageable_organization_ids_for_user(request.user)
    manageable_ids = None if manageable_ids is None else set(manageable_ids)
    job_rows = []
    for j in jobs:
        slug = j.device.organization.slug
        did = j.device.device_id
        job_rows.append(
            {
                "job_id": str(j.job_id),
                "device_name": j.device.name,
                "org_slug": slug,
                "device_product": j.device.firmware_product,
                "firmware": str(j.firmware),
                "status": j.get_status_display(),
                "status_key": j.status,
                "created": j.created_at,
                "edit_href": snippet_edit_url("deviceotajob", j.pk) if request.user.is_superuser else None,
                "downlink_topic": build_device_topic(j.device, "down", "ota"),
                "can_manage": manageable_ids is None or j.device.organization_id in manageable_ids,
            }
        )

    dev_opts = [
        {
            "pk": d.pk,
            "profile_pk": d.profile_id or "",
            "label": f"{d.organization.slug} / {d.name} [profile={d.profile or 'none'}] ({d.device_id})",
        }
        for d in scope_manageable_devices(Device.objects.select_related("organization", "profile"), request.user).order_by(
            "organization__name", "name"
        )[:2000]
    ]
    fw_opts = [
        {
            "pk": f.pk,
            "profile_pk": f.profile_id or "",
            "label": f"{f.profile or 'Legacy / unmapped'} @ {f.version}",
        }
        for f in FirmwarePackage.objects.filter(is_active=True, profile__isnull=False)
        .select_related("profile", "profile__organization")
        .order_by("profile__name", "-created_at")[:2000]
    ]
    ota_base = ota_services.get_ota_public_base_url()

    return TemplateResponse(
        request,
        "IoT/admin/panel_ota.html",
        {
            "title": "OTA — IoT",
            "job_rows": job_rows,
            "device_options": dev_opts,
            "firmware_options": fw_opts,
            "ota_public_base": ota_base,
            "snips": all_snippet_links(request.user).get("firmwareversion", {}),
            "job_snip": all_snippet_links(request.user).get("deviceotajob", {}),
            **_base_iot_context("ota", request.user),
        },
    )


@require_admin_access
@require_GET
def api_mqtt_bridge_status(request):
    from apps.mqtt.client import mqtt_client

    return JsonResponse(
        {
            "connected": bool(mqtt_client.is_connected),
            "active_topics": getattr(mqtt_client, "active_topics", []),
        }
    )


@require_admin_access
@require_GET
def api_device_mqtt_messages(request, device_pk: int):
    try:
        limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    d = get_object_or_404(
        scope_devices(Device.objects.select_related("organization"), request.user), pk=device_pk
    )
    prefix, messages = services.recent_mqtt_messages_for_device(d, limit=limit)
    return JsonResponse(
        {
            "device": str(d.device_id),
            "name": d.name,
            "org_slug": d.organization.slug,
            "prefix": prefix,
            "count": len(messages),
            "messages": messages,
        }
    )


@require_admin_access
@require_GET
def api_devices_summary(request):
    data = []
    for d in scope_devices(Device.objects.select_related("organization"), request.user).all()[:500]:
        data.append(
            {
                "id": str(d.device_id),
                "name": d.name,
                "org": d.organization.slug,
                "online": services.device_is_online(d),
                "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
        )
    return JsonResponse({"devices": data, "count": len(data)})


@require_admin_access
@require_http_methods(["POST"])
def api_envelope_preview(request):
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON body"}, status=400)
    raw = body.get("raw", "")
    if not isinstance(raw, str):
        return JsonResponse({"ok": False, "error": "Field 'raw' must be a string"}, status=400)
    env, err = services.validate_envelope(raw)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=200)
    return JsonResponse(
        {
            "ok": True,
            "envelope": {k: v for k, v in (env or {}).items() if not k.startswith("_")},
        }
    )
