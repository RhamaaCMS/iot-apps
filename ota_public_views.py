"""
Public OTA download (signed query ?t=) — for devices, not the Wagtail admin.
"""

from __future__ import annotations

import uuid

from django.core import signing
from django.http import (
    FileResponse,
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
)
from django.shortcuts import get_object_or_404

from .constants import OTA_DOWNLOAD_SALT
from .models import DeviceOTAJob, OTAJobStatus


def ota_public_download(request):
    if request.method == "GET":
        pass
    else:
        return HttpResponseNotAllowed(["GET", "HEAD"])

    t = (request.GET.get("t") or "").strip()
    if not t:
        return HttpResponseBadRequest("Missing t.")

    try:
        data = signing.loads(t, salt=OTA_DOWNLOAD_SALT, max_age=7 * 24 * 3600)
    except signing.BadSignature:
        return HttpResponseForbidden("Invalid or expired link.")
    try:
        jid = uuid.UUID(str(data["jid"]).strip())
    except (KeyError, TypeError, ValueError):
        return HttpResponseForbidden("Bad token payload.")
    d_raw = str(data.get("d") or "").strip()
    if not d_raw:
        return HttpResponseForbidden("Bad token payload.")

    job = get_object_or_404(
        DeviceOTAJob.objects.select_related("firmware", "device"), job_id=jid
    )
    if str(job.device.device_id) != d_raw:
        return HttpResponseForbidden("Device mismatch.")
    if job.status not in (
        OTAJobStatus.PENDING,
        OTAJobStatus.SENT,
        OTAJobStatus.IN_PROGRESS,
    ):
        return HttpResponseForbidden("This job is not available for download anymore.")

    fw = job.firmware
    if not getattr(fw, "file", None) or not fw.file.name:
        raise Http404()

    from pathlib import Path

    name = Path(fw.file.name).name
    return FileResponse(fw.file.open("rb"), as_attachment=True, filename=name)
