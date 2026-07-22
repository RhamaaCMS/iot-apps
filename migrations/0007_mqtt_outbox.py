import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("iot", "0006_connected_device_foundation")]

    operations = [
        migrations.CreateModel(
            name="MQTTOutboxMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("topic", models.CharField(max_length=500)),
                ("payload", models.TextField()),
                ("qos", models.PositiveSmallIntegerField(default=1)),
                ("retain", models.BooleanField(default=False)),
                ("event_type", models.CharField(blank=True, max_length=50)),
                ("reference_id", models.UUIDField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("processing", "Processing"), ("sent", "Sent"), ("failed", "Failed")], default="pending", max_length=20)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("available_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ],
            options={"ordering": ("created_at",)},
        ),
        migrations.AddIndex(
            model_name="mqttoutboxmessage",
            index=models.Index(fields=["status", "available_at", "created_at"], name="iot_mqttout_status_f0ce99_idx"),
        ),
        migrations.AddConstraint(
            model_name="mqttoutboxmessage",
            constraint=models.UniqueConstraint(condition=models.Q(("reference_id__isnull", False)), fields=("event_type", "reference_id"), name="iot_outbox_event_reference_uniq"),
        ),
    ]
