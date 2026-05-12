import json
import uuid
from datetime import UTC

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_GET, require_http_methods
from wagtail.admin.auth import require_admin_access
from django.contrib import messages
from . import ota_services
from . import services
from .admin_snippet_urls import all_snippet_links, snippet_edit_url
from .constants import (
    ALLOWED_SCHEMAS,
    ENVELOPE_VERSION,
    IOT_MQTT_TOPIC_PREFIX,
    ONLINE_THRESHOLD_MINUTES,
)
from .models import Device, DeviceOTAJob, FirmwareVersion, Organization, OrganizationMembership

# Backward compatibility alias
FirmwarePackage = FirmwareVersion


def _base_iot_context(active_section: str) -> dict:
    return {
        "iot_active_section": active_section,
        "snippets": all_snippet_links(),
    }


@require_admin_access
def dashboard(request):
    org_count = Organization.objects.filter(is_active=True).count()
    dev_qs = Device.objects.select_related("organization")
    dev_count = dev_qs.count()
    online = sum(1 for d in dev_qs if services.device_is_online(d))
    devices = []
    preview_n = 8
    for d in dev_qs[:preview_n]:
        devices.append(
            {
                "name": d.name,
                "org_slug": d.organization.slug,
                "device_id": str(d.device_id),
                "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None,
                "online": services.device_is_online(d),
                "last_channel": d.last_channel or "—",
                "last_schema": d.last_schema or "—",
            }
        )
    from django.utils import timezone

    return TemplateResponse(
        request,
        "IoT/admin/dashboard.html",
        {
            "title": "IoT",
            "org_count": org_count,
            "device_count": dev_count,
            "online_count": online,
            "online_threshold_minutes": ONLINE_THRESHOLD_MINUTES,
            "devices": devices,
            "devices_preview_limit": preview_n,
            "has_more_devices": dev_count > preview_n,
            "envelope_version": ENVELOPE_VERSION,
            "topic_prefix": IOT_MQTT_TOPIC_PREFIX,
            "allowed_schemas": list(ALLOWED_SCHEMAS),
            "example_telemetry_topic": f"{IOT_MQTT_TOPIC_PREFIX}/kirei/550e8400-e29b-41d4-a716-446655440000/up/telemetry",
            "now_iso": timezone.now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
            **_base_iot_context("summary"),
        },
    )


@require_admin_access
def panel_organizations(request):
    orgs = (
        Organization.objects.annotate(_num_devices=Count("devices", distinct=True))
        .order_by("name")
    )
    rows = []
    for o in orgs:
        rows.append(
            {
                "pk": o.pk,
                "name": o.name,
                "slug": o.slug,
                "is_active": o.is_active,
                "num_devices": o._num_devices,
                "edit_href": snippet_edit_url("organization", o.pk),
            }
        )
    return TemplateResponse(
        request,
        "IoT/admin/panel_organizations.html",
        {
            "title": "Organisasi — IoT",
            "rows": rows,
            "row_count": len(rows),
            **_base_iot_context("organizations"),
        },
    )


@require_admin_access
def panel_memberships(request):
    q = OrganizationMembership.objects.select_related(
        "user", "organization"
    ).order_by("organization__name", "user__email")
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
                "edit_href": snippet_edit_url("organizationmembership", m.pk),
            }
        )
    return TemplateResponse(
        request,
        "IoT/admin/panel_memberships.html",
        {
            "title": "Pengguna & organisasi — IoT",
            "rows": rows,
            "row_count": len(rows),
            **_base_iot_context("memberships"),
        },
    )


@require_admin_access
def panel_devices(request):
    dev_qs = Device.objects.select_related("organization").order_by(
        "organization__name", "name"
    )
    rows = []
    for d in dev_qs:
        rows.append(
            {
                "pk": d.pk,
                "name": d.name,
                "org_slug": d.organization.slug,
                "org_name": d.organization.name,
                "device_id": str(d.device_id),
                "firmware_product": d.firmware_product,
                "is_active": d.is_active,
                "online": services.device_is_online(d),
                "last_seen": d.last_seen_at,
                "last_channel": d.last_channel or "—",
                "last_schema": d.last_schema or "—",
                "edit_href": snippet_edit_url("device", d.pk),
                "topic_filter_prefix": services.device_mqtt_message_topic_prefix(d),
            }
        )
    return TemplateResponse(
        request,
        "IoT/admin/panel_devices.html",
        {
            "title": "Perangkat — IoT",
            "rows": rows,
            "row_count": len(rows),
            "online_threshold_minutes": ONLINE_THRESHOLD_MINUTES,
            **_base_iot_context("devices"),
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
                Device.objects.select_related("organization"), pk=dev_pk
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
                DeviceOTAJob.objects.select_related("device", "firmware", "device__organization"),
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
                    f"OTA command published for job {job.job_id}.",
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
                DeviceOTAJob.objects.select_related("device", "firmware", "device__organization"),
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
                    f"OTA command re-sent for job {job.job_id} (new signed URL).",
                )
            return redirect("iot:panel_ota")

    jobs = (
        DeviceOTAJob.objects.select_related("device", "device__organization", "firmware")
        .order_by("-created_at")[:80]
    )
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
                "edit_href": snippet_edit_url("deviceotajob", j.pk),
                "downlink_topic": f"{IOT_MQTT_TOPIC_PREFIX}/{slug}/{did}/down/ota",
            }
        )

    dev_opts = [
        {
            "pk": d.pk,
            "label": f"{d.organization.slug} / {d.name} [product={d.firmware_product}] ({d.device_id})",
        }
        for d in Device.objects.select_related("organization").order_by(
            "organization__name", "name"
        )[:2000]
    ]
    fw_opts = [
        {
            "pk": f.pk,
            "label": f"{f.product} @ {f.version} (active={f.is_active})",
        }
        for f in FirmwarePackage.objects.filter(is_active=True).order_by("-created_at")[:2000]
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
            "snips": all_snippet_links().get("firmwarepackage", {}),
            "job_snip": all_snippet_links().get("deviceotajob", {}),
            **_base_iot_context("ota"),
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
        Device.objects.select_related("organization"), pk=device_pk
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
    for d in Device.objects.select_related("organization").all()[:500]:
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
