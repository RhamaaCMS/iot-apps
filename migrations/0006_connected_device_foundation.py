import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("iot", "0005_firmware_version_upgrade")]

    operations = [
        migrations.CreateModel(
            name="DeviceProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField(max_length=100)),
                ("product_code", models.CharField(blank=True, max_length=100)),
                ("allowed_schemas", models.JSONField(blank=True, default=list, help_text="Allowed uplink schemas. Empty means any valid schema.")),
                ("heartbeat_interval_seconds", models.PositiveIntegerField(default=300)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="device_profiles", to="iot.organization")),
            ],
            options={"ordering": ("organization__name", "name")},
        ),
        migrations.AddConstraint(model_name="deviceprofile", constraint=models.UniqueConstraint(fields=("organization", "slug"), name="iot_profile_org_slug_uniq")),
        migrations.AddField(model_name="device", name="claimed_at", field=models.DateTimeField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name="device", name="last_device_timestamp", field=models.DateTimeField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name="device", name="profile", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="devices", to="iot.deviceprofile")),
        migrations.CreateModel(
            name="DeviceCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("credential_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("secret_hash", models.CharField(editable=False, max_length=255)),
                ("status", models.CharField(choices=[("active", "Active"), ("revoked", "Revoked")], default="active", max_length=20)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("last_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="credentials", to="iot.device")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="ProvisioningToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("secret_hash", models.CharField(editable=False, max_length=255)),
                ("label", models.CharField(blank=True, max_length=255)),
                ("max_claims", models.PositiveIntegerField(default=1)),
                ("claim_count", models.PositiveIntegerField(default=0, editable=False)),
                ("expires_at", models.DateTimeField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="provisioning_tokens", to="iot.organization")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="provisioning_tokens", to="iot.deviceprofile")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="DeviceState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("desired", models.JSONField(blank=True, default=dict)),
                ("reported", models.JSONField(blank=True, default=dict)),
                ("desired_version", models.PositiveBigIntegerField(default=0)),
                ("reported_version", models.PositiveBigIntegerField(default=0)),
                ("desired_updated_at", models.DateTimeField(blank=True, null=True)),
                ("reported_updated_at", models.DateTimeField(blank=True, null=True)),
                ("device", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="state", to="iot.device")),
            ],
        ),
        migrations.CreateModel(
            name="DeviceCommand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("command_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sent", "Sent"), ("acknowledged", "Acknowledged"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("timed_out", "Timed out"), ("cancelled", "Cancelled")], default="pending", max_length=20)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="commands", to="iot.device")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(model_name="devicecommand", index=models.Index(fields=["device", "status", "created_at"], name="iot_devicec_device__066551_idx")),
        migrations.CreateModel(
            name="TelemetryRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.CharField(blank=True, max_length=128, null=True)),
                ("channel", models.CharField(max_length=100)),
                ("schema", models.CharField(max_length=200)),
                ("payload", models.JSONField(default=dict)),
                ("device_timestamp", models.DateTimeField()),
                ("received_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="telemetry_records", to="iot.device")),
            ],
            options={"ordering": ("-received_at",)},
        ),
        migrations.AddIndex(model_name="telemetryrecord", index=models.Index(fields=["device", "received_at"], name="iot_teleme_device__c906fd_idx")),
        migrations.AddIndex(model_name="telemetryrecord", index=models.Index(fields=["schema", "received_at"], name="iot_teleme_schema_2c4ddf_idx")),
        migrations.AddConstraint(model_name="telemetryrecord", constraint=models.UniqueConstraint(condition=models.Q(("message_id__isnull", False)), fields=("device", "message_id"), name="iot_telemetry_device_message_uniq")),
        migrations.CreateModel(
            name="DeviceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(max_length=100)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("device", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="events", to="iot.device")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="device_events", to="iot.organization")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(model_name="deviceevent", index=models.Index(fields=["organization", "event_type", "created_at"], name="iot_devicee_organiz_31e3f9_idx")),
    ]
