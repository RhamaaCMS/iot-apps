from django.db import migrations, models
import django.db.models.deletion


def map_unambiguous_firmware_profiles(apps, schema_editor):
    DeviceProfile = apps.get_model("iot", "DeviceProfile")
    FirmwareVersion = apps.get_model("iot", "FirmwareVersion")

    for firmware in FirmwareVersion.objects.filter(profile__isnull=True).iterator():
        matches = DeviceProfile.objects.filter(product_code=firmware.product)
        if matches.count() != 1:
            matches = DeviceProfile.objects.filter(slug=firmware.product)
        if matches.count() == 1:
            FirmwareVersion.objects.filter(pk=firmware.pk).update(
                profile_id=matches.values_list("pk", flat=True).first()
            )


class Migration(migrations.Migration):
    dependencies = [
        ("iot", "0009_rename_iot_devicec_device__066551_idx_iot_devicec_device__c73f4e_idx_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="firmwareversion",
            name="iot_firmware_version_product_version_uniq",
        ),
        migrations.AddField(
            model_name="firmwareversion",
            name="profile",
            field=models.ForeignKey(
                blank=True,
                help_text="Device profile that owns this firmware version.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="firmware_versions",
                to="iot.deviceprofile",
            ),
        ),
        migrations.RunPython(
            map_unambiguous_firmware_profiles,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="firmwareversion",
            constraint=models.UniqueConstraint(
                fields=("profile", "version"),
                name="iot_firmware_profile_version_uniq",
            ),
        ),
    ]
