from django.http import HttpRequest, HttpResponse

from apps.IoT.constants import IOT_MQTT_TOPIC_PREFIX, ENVELOPE_VERSION


def index(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        f"IoT module (envelope v{ENVELOPE_VERSION}, topic prefix {IOT_MQTT_TOPIC_PREFIX!r}). "
        "Wagtail admin: /admin/iot/",
        content_type="text/plain; charset=utf-8",
    )
