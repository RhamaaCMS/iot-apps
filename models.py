import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, FieldRowPanel, HelpPanel, MultiFieldPanel
from wagtail.snippets.models import register_snippet


@register_snippet
class Organization(models.Model):
    """Root tenant; `org` in the MQTT JSON must match `slug` (auto from `name`)."""

    class Meta:
        app_label = "iot"
        verbose_name = _("Organization")
        verbose_name_plural = _("Organizations")
        ordering = ("name",)

    name = models.CharField(
        max_length=255,
        help_text=_("Nama unik; tidak boleh sama dengan organisasi lain (abaikan huruf besar/kecil)."),
    )
    slug = models.SlugField(
        max_length=255,
        unique=True,
        blank=True,
        help_text=_("Dibuat otomatis dari nama. Dipakai di topik MQTT: iot/v1/{slug}/…"),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    panels = [
        FieldPanel("name"),
        FieldPanel("slug", read_only=True),
        FieldPanel("is_active"),
        HelpPanel(
            content=_(
                "Field <b>org</b> pada envelope MQTT harus sama dengan <b>slug</b> di bawah. "
                "Slug diperbarui otomatis saat nama disimpan; ubah nama hanya bila memang perlu mengganti topik perangkat."
            ),
        ),
    ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        if self.name is not None:
            self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": _("Nama organisasi wajib diisi.")})
        others = Organization.objects.filter(name__iexact=self.name)
        if self.pk:
            others = others.exclude(pk=self.pk)
        if others.exists():
            raise ValidationError(
                {"name": _("Sudah ada organisasi dengan nama yang sama.")}
            )

    def _make_unique_slug(self) -> str:
        base = (slugify(self.name) or "").strip("-")
        if not base:
            base = f"org-{uuid.uuid4().hex[:8]}"
        base = base[:200]
        candidate = base
        n = 1
        qs = Organization.objects.all()
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        while qs.filter(slug=candidate).exists():
            n += 1
            suffix = f"-{n}"
            candidate = f"{base}{suffix}"[:255]
        return candidate

    def save(self, *args, **kwargs):
        skip_validation = kwargs.pop("skip_validation", False)
        if self.name:
            self.name = self.name.strip()
        if not skip_validation:
            self.full_clean()
        if self.name:
            self.slug = self._make_unique_slug()
        super().save(*args, **kwargs)


class MemberRole(models.TextChoices):
    ADMIN = "admin", _("Admin")
    MEMBER = "member", _("Member")
    VIEWER = "viewer", _("Viewer")


@register_snippet
class OrganizationMembership(models.Model):
    """User ↔ organization access for IoT data and admin."""

    class Meta:
        app_label = "iot"
        verbose_name = _("Organization membership")
        verbose_name_plural = _("Organization memberships")
        ordering = ("organization__name", "user__email")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "organization"),
                name="iot_membership_user_org_uniq",
            )
        ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="iot_memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=MemberRole.choices,
        default=MemberRole.MEMBER,
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    panels = [
        FieldPanel("user"),
        FieldPanel("organization"),
        FieldPanel("role"),
    ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"


@register_snippet
class Device(models.Model):
    """Physical or logical device; `device_id` is the global UUID in topics + JSON."""

    class Meta:
        app_label = "iot"
        verbose_name = _("Device")
        verbose_name_plural = _("Devices")
        ordering = ("organization", "name")
        indexes = [
            models.Index(fields=["organization", "device_id"]),
        ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="devices",
    )
    name = models.CharField(max_length=255)
    device_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        help_text="Must match the device_id segment in MQTT and in the JSON envelope.",
    )
    is_active = models.BooleanField(default=True)
    topic_prefix = models.CharField(
        max_length=500,
        blank=True,
        help_text="Optional override; leave empty to use iot/v1/{org_slug}/{device_id}/…",
    )
    firmware_product = models.CharField(
        max_length=100,
        default="default",
        help_text=_("Must match FirmwarePackage.product for OTA (e.g. hardware SKU)."),
    )
    last_seen_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_channel = models.CharField(max_length=100, blank=True, editable=False)
    last_schema = models.CharField(max_length=200, blank=True, editable=False)
    hardware_version = models.CharField(
        max_length=32,
        blank=True,
        help_text=_("Hardware revision (e.g., 'rev2', 'v1.1') for firmware compatibility checks."),
    )
    reported_firmware_version = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Set after successful OTA (device report)."),
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    panels = [
        MultiFieldPanel(
            [FieldPanel("organization"), FieldPanel("name")],
            heading="Identity",
        ),
        FieldPanel("device_id"),
        FieldPanel("is_active"),
        FieldPanel("topic_prefix"),
        FieldPanel("firmware_product"),
        FieldPanel("hardware_version"),
        FieldPanel("reported_firmware_version", read_only=True),
        MultiFieldPanel(
            [
                FieldPanel("last_seen_at", read_only=True),
                FieldPanel("last_channel", read_only=True),
                FieldPanel("last_schema", read_only=True),
            ],
            heading="Last uplink (from MQTT handler)",
        ),
    ]

    def __str__(self) -> str:
        return f"{self.name} ({self.device_id})"


class OTAJobStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SENT = "sent", _("Command sent (MQTT)")
    IN_PROGRESS = "in_progress", _("In progress (device)")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    CANCELLED = "cancelled", _("Cancelled")


def firmware_upload_path(instance, filename):
    """
    Generate upload path: iot/firmware/{product_slug}/{version}/{hash_prefix}_{filename}
    Ensures unique folder per version and prevents filename collisions.
    """
    import hashlib
    import os

    # Get product slug (safe for filesystem)
    product_slug = slugify(instance.product) or "default"

    # Get version (safe for filesystem)
    version_slug = slugify(instance.version) or "unknown"

    # Generate short hash from file content (if available) or timestamp
    if instance.file and hasattr(instance.file, 'temporary_file_path'):
        # For new uploads, hash a small chunk
        try:
            instance.file.seek(0)
            chunk = instance.file.read(1024)
            instance.file.seek(0)
            hash_prefix = hashlib.md5(chunk).hexdigest()[:8]
        except Exception:
            hash_prefix = hashlib.md5(str(timezone.now().timestamp()).encode()).hexdigest()[:8]
    else:
        hash_prefix = hashlib.md5(str(timezone.now().timestamp()).encode()).hexdigest()[:8]

    # Sanitize filename
    safe_filename = os.path.basename(filename).replace(" ", "_")

    # Build path: iot/firmware/{product}/{version}/{hash}_{filename}
    return f"iot/firmware/{product_slug}/{version_slug}/{hash_prefix}_{safe_filename}"


@register_snippet
class FirmwareVersion(models.Model):
    """
    Firmware version definition with binary file storage.
    Each version is stored in its own folder to prevent file collisions.
    """

    class Meta:
        app_label = "iot"
        verbose_name = _("Firmware Version")
        verbose_name_plural = _("Firmware Versions")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("product", "version"),
                name="iot_firmware_version_product_version_uniq",
            )
        ]

    product = models.CharField(
        max_length=100,
        default="default",
        help_text=_("Product SKU or hardware type (e.g., 'solar-controller-v2')."),
        db_index=True,
    )
    version = models.CharField(
        max_length=64,
        help_text=_("Semantic version (e.g., 1.4.0, 2.0.0-beta.1)."),
        db_index=True,
    )
    file = models.FileField(
        upload_to=firmware_upload_path,
        help_text=_("Firmware binary file (.bin, .elf, .hex). Stored in isolated folder per version."),
    )
    sha256 = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        help_text=_("SHA256 hash of the file for integrity verification."),
    )
    file_size = models.PositiveIntegerField(
        default=0,
        editable=False,
        help_text=_("File size in bytes."),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Only active versions can be deployed via OTA."),
    )
    is_mandatory = models.BooleanField(
        default=False,
        help_text=_("Mark as mandatory update - devices will be forced to update."),
    )
    release_notes = models.TextField(
        blank=True,
        help_text=_("Release notes describing changes in this version."),
    )
    min_hardware_version = models.CharField(
        max_length=32,
        blank=True,
        help_text=_("Minimum hardware version required (e.g., 'rev2'). Leave empty for all."),
    )
    max_hardware_version = models.CharField(
        max_length=32,
        blank=True,
        help_text=_("Maximum hardware version supported (e.g., 'rev4'). Leave empty for all."),
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="created_firmware_versions",
    )

    panels = [
        MultiFieldPanel(
            [
                FieldPanel("product"),
                FieldPanel("version"),
            ],
            heading="Version Identity",
        ),
        MultiFieldPanel(
            [
                FieldPanel("file"),
                FieldPanel("is_active"),
                FieldPanel("is_mandatory"),
            ],
            heading="Firmware Binary",
        ),
        MultiFieldPanel(
            [
                FieldPanel("min_hardware_version"),
                FieldPanel("max_hardware_version"),
            ],
            heading="Hardware Compatibility",
        ),
        FieldPanel("release_notes"),
        MultiFieldPanel(
            [
                FieldPanel("sha256", read_only=True),
                FieldPanel("file_size", read_only=True),
                FieldPanel("created_at", read_only=True),
            ],
            heading="Metadata",
        ),
    ]

    def __str__(self) -> str:
        return f"{self.product}@{self.version}"

    @property
    def display_name(self) -> str:
        """Full display name with status indicators."""
        flags = []
        if not self.is_active:
            flags.append("[INACTIVE]")
        if self.is_mandatory:
            flags.append("[MANDATORY]")
        flag_str = " ".join(flags)
        return f"{self.product}@{self.version} {flag_str}".strip()

    @property
    def storage_path(self) -> str:
        """Return the storage path for this firmware file."""
        if self.file:
            return self.file.name
        return ""

    @property
    def folder_name(self) -> str:
        """Return the folder name where this firmware is stored."""
        if self.file and self.file.name:
            parts = self.file.name.split("/")
            if len(parts) >= 3:
                return f"{parts[2]}/{parts[3]}"  # product/version
        return ""

    def clean(self) -> None:
        super().clean()
        from .constants import OTA_MAX_FIRMWARE_BYTES

        # Validate file size
        if self.file and hasattr(self.file, "size") and self.file.size:
            if self.file.size > OTA_MAX_FIRMWARE_BYTES:
                raise ValidationError(
                    {"file": _("File is too large (max %(mb)s MB).") % {"mb": OTA_MAX_FIRMWARE_BYTES // (1024 * 1024)}}
                )
            # Validate file extension
            allowed_exts = {'.bin', '.elf', '.hex', '.fw', '.img'}
            filename = str(self.file.name).lower()
            if not any(filename.endswith(ext) for ext in allowed_exts):
                raise ValidationError(
                    {"file": _("File must have extension: %(exts)s") % {"exts": ", ".join(allowed_exts)}}
                )

        # Validate hardware version constraints
        if self.min_hardware_version and self.max_hardware_version:
            if self.min_hardware_version > self.max_hardware_version:
                raise ValidationError(
                    {"max_hardware_version": _("Max version must be greater than or equal to min version.")}
                )

    def _calculate_hash_and_size(self):
        """Calculate SHA256 hash and file size from the uploaded file."""
        import hashlib

        if not self.file:
            return

        try:
            self.file.open("rb")
        except Exception:
            return

        h = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: self.file.read(65536), b""):
            h.update(chunk)
            size += len(chunk)

        self.sha256 = h.hexdigest()
        self.file_size = size

        try:
            self.file.seek(0)
        except Exception:
            pass

    def save(self, *args, **kwargs) -> None:
        # Calculate hash and size before saving
        self._calculate_hash_and_size()
        super().save(*args, **kwargs)

    def is_compatible_with_device(self, device) -> bool:
        """Check if this firmware version is compatible with a given device."""
        # Check product match
        dev_product = (device.firmware_product or "").strip() or "default"
        if (self.product or "").strip() != dev_product:
            return False

        # Check hardware version constraints if device has hardware version info
        hw_version = getattr(device, 'hardware_version', '')
        if hw_version:
            if self.min_hardware_version and hw_version < self.min_hardware_version:
                return False
            if self.max_hardware_version and hw_version > self.max_hardware_version:
                return False

        return True


# Backward compatibility: FirmwarePackage alias untuk kode lama
FirmwarePackage = FirmwareVersion


@register_snippet
class DeviceOTAJob(models.Model):
    """One OTA update attempt for a device (MQTT downlink + device status uplink)."""

    class Meta:
        app_label = "iot"
        verbose_name = _("Device OTA job")
        verbose_name_plural = _("Device OTA jobs")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="ota_jobs",
    )
    firmware = models.ForeignKey(
        FirmwarePackage,
        on_delete=models.PROTECT,
        related_name="ota_jobs",
    )
    job_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    status = models.CharField(
        max_length=20,
        choices=OTAJobStatus.choices,
        default=OTAJobStatus.PENDING,
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    command_sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)

    panels = [
        FieldPanel("device", read_only=True),
        FieldPanel("firmware", read_only=True),
        FieldPanel("job_id", read_only=True),
        FieldPanel("status", read_only=True),
        FieldPanel("error_message", read_only=True),
        FieldRowPanel(
            [FieldPanel("command_sent_at", read_only=True), FieldPanel("completed_at", read_only=True)],
        ),
    ]

    def __str__(self) -> str:
        return f"OTA {self.device.device_id} → {self.firmware} [{self.get_status_display()}]"
