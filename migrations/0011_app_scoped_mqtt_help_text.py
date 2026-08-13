from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("iot", "0010_firmware_profile_ownership"),
    ]

    operations = [
        migrations.AlterField(
            model_name="device",
            name="topic_prefix",
            field=models.CharField(
                blank=True,
                help_text="Optional override inside iot/v2/{app_id}/; leave empty for the canonical namespace.",
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="slug",
            field=models.SlugField(
                blank=True,
                help_text="Dibuat otomatis dari nama. Dipakai setelah app_id pada namespace MQTT.",
                max_length=255,
                unique=True,
            ),
        ),
    ]
