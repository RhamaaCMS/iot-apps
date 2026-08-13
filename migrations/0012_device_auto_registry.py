import django.db.models.deletion
import uuid

from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [("iot", "0011_app_scoped_mqtt_help_text")]

    operations = [
        migrations.AddField(
            model_name="deviceprofile",
            name="schema_contracts",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Normalized JSON shapes per schema, used for automatic device matching.",
            ),
        ),
        migrations.AlterField(
            model_name="provisioningtoken",
            name="profile",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional for auto-registry tokens; profile is inferred from data shape.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="provisioning_tokens",
                to="iot.deviceprofile",
            ),
        ),
        migrations.CreateModel(
            name="DeviceRegistrationRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("credential_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("secret_hash", models.CharField(editable=False, max_length=255)),
                ("hardware_id", models.CharField(max_length=100)),
                ("requested_name", models.CharField(max_length=255)),
                ("hardware_version", models.CharField(blank=True, max_length=32)),
                ("firmware_product", models.CharField(blank=True, max_length=100)),
                ("firmware_version", models.CharField(blank=True, max_length=100)),
                ("schema", models.CharField(max_length=200)),
                ("sample_data", models.JSONField(default=dict)),
                ("data_shape", models.JSONField(default=dict, editable=False)),
                ("status", models.CharField(choices=[("pending", "Pending review"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=20)),
                ("rejection_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=timezone.now, editable=False)),
                ("reviewed_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("device", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="registration_request", to="iot.device")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="registration_requests", to="iot.organization")),
                ("provisioning_token", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registration_requests", to="iot.provisioningtoken")),
                ("suggested_profile", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="suggested_registrations", to="iot.deviceprofile")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddConstraint(
            model_name="deviceregistrationrequest",
            constraint=models.UniqueConstraint(fields=("provisioning_token", "hardware_id"), name="iot_registry_token_hardware_uniq"),
        ),
    ]
