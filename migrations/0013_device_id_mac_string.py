import apps.IoT.models

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("iot", "0012_device_auto_registry")]

    operations = [
        migrations.AlterField(
            model_name="device",
            name="device_id",
            field=models.CharField(
                db_index=True,
                default=apps.IoT.models.default_device_id,
                help_text="Auto-registry uses ESP32 STA MAC without separators (AABBCCDDEEFF).",
                max_length=64,
                unique=True,
            ),
        ),
    ]
