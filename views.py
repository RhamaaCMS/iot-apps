import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .constants import ENVELOPE_VERSION, get_iot_app_id, mqtt_topic_root

logger = logging.getLogger(__name__)


def _client_ip(request: HttpRequest) -> str:
    # REMOTE_ADDR is intentional; trusted proxy normalization belongs in project middleware.
    return request.META.get("REMOTE_ADDR", "unknown")


def _provision_rate_limited(request: HttpRequest) -> bool:
    limit = int(getattr(settings, "IOT_PROVISION_RATE_LIMIT", 10))
    key = f"iot:provision:{_client_ip(request)}"
    if cache.add(key, 1, timeout=60):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        cache.set(key, 1, timeout=60)
        return False


def index(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        f"IoT module {get_iot_app_id()!r} (envelope v{ENVELOPE_VERSION}, topic root {mqtt_topic_root()!r}). "
        "Wagtail admin: /admin/iot/",
        content_type="text/plain; charset=utf-8",
    )


@csrf_exempt
@require_POST
def provision(request: HttpRequest) -> JsonResponse:
    """Claim endpoint. Bootstrap token is exchanged once for device credential."""
    if len(request.body) > 8192:
        return JsonResponse({"ok": False, "error": "Request too large."}, status=413)
    if _provision_rate_limited(request):
        logger.warning("IoT provisioning rate limited ip=%s", _client_ip(request))
        response = JsonResponse({"ok": False, "error": "Too many requests."}, status=429)
        response["Retry-After"] = "60"
        return response
    try:
        body = json.loads(request.body or b"{}")
        token = body["token"]
        app_id = body["app_id"]
        name = body.get("name", "")
        hardware_version = body.get("hardware_version", "")
        if not all(isinstance(value, str) for value in (token, app_id, name, hardware_version)):
            raise ValueError
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid request."}, status=400)
    if app_id.strip().lower() != get_iot_app_id():
        logger.warning("IoT provisioning rejected foreign app_id ip=%s", _client_ip(request))
        return JsonResponse({"ok": False, "error": "App identity mismatch."}, status=403)
    from .device_services import claim_device

    try:
        device, credential = claim_device(token, name=name, hardware_version=hardware_version)
    except ValidationError:
        logger.warning("IoT provisioning denied ip=%s", _client_ip(request))
        return JsonResponse({"ok": False, "error": "Provisioning denied."}, status=403)
    response = JsonResponse(
        {
            "ok": True,
            "device_id": str(device.device_id),
            "app_id": get_iot_app_id(),
            "organization": device.organization.slug,
            "credential": credential,
            "topic_prefix": f"{mqtt_topic_root()}/{device.organization.slug}/{device.device_id}",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response

@csrf_exempt
@require_POST
def registry(request: HttpRequest) -> JsonResponse:
    """One-call ESP32 registration using its STA MAC as device_id."""
    if len(request.body) > 32768:
        return JsonResponse({"ok": False, "error": "Request too large."}, status=413)
    if _provision_rate_limited(request):
        return JsonResponse({"ok": False, "error": "Too many requests."}, status=429)
    try:
        body = json.loads(request.body or b"{}")
        if str(body.get("app_id", "")).strip().lower() != get_iot_app_id():
            return JsonResponse({"ok": False, "error": "App identity mismatch."}, status=403)
        raw_token = body["token"]
        credential_secret = body["credential_secret"]
        if not isinstance(raw_token, str) or not isinstance(credential_secret, str):
            raise ValueError
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid request."}, status=400)
    from .registry_services import auto_register_device

    try:
        registration, created = auto_register_device(
            raw_token=raw_token, credential_secret=credential_secret, manifest=body
        )
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": exc.messages[0]}, status=403)
    response = JsonResponse(
        {
            "ok": True,
            "created": created,
            "status": "registered",
            "app_id": get_iot_app_id(),
            "organization": registration.device.organization.slug,
            "device_id": str(registration.device.device_id),
            "profile": registration.device.profile.slug,
            "credential": f"{registration.credential_id}.{credential_secret}",
            "topic_prefix": f"{mqtt_topic_root()}/{registration.device.organization.slug}/{registration.device.device_id}",
        },
        status=201 if created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response
