from django.core.exceptions import ValidationError
from django.test import TestCase

from ..models import Device, DeviceProfile, FirmwareVersion, Organization
from ..ota_services import create_ota_job, get_compatible_firmware_for_device


class OTAProfileOwnershipTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Factory")
        self.sensor_profile = DeviceProfile.objects.create(
            organization=self.organization,
            name="Sensor Node",
            slug="sensor-node",
            product_code="sensor-v1",
        )
        self.gateway_profile = DeviceProfile.objects.create(
            organization=self.organization,
            name="Gateway",
            slug="gateway",
            product_code="gateway-v1",
        )
        self.device = Device.objects.create(
            organization=self.organization,
            profile=self.sensor_profile,
            name="Sensor 01",
        )
        self.sensor_firmware = FirmwareVersion.objects.create(
            profile=self.sensor_profile,
            version="1.0.0",
            file="iot/firmware/sensor-v1/1.0.0/sensor.bin",
            sha256="a" * 64,
        )
        self.gateway_firmware = FirmwareVersion.objects.create(
            profile=self.gateway_profile,
            version="1.0.0",
            file="iot/firmware/gateway-v1/1.0.0/gateway.bin",
            sha256="b" * 64,
        )

    def test_compatible_firmware_is_limited_to_exact_profile(self):
        compatible = get_compatible_firmware_for_device(self.device)

        self.assertQuerySetEqual(compatible, [self.sensor_firmware])

    def test_ota_rejects_firmware_from_another_profile(self):
        with self.assertRaisesMessage(
            ValidationError, "Firmware belongs to a different device profile."
        ):
            create_ota_job(self.device, self.gateway_firmware)

    def test_device_product_is_derived_from_profile(self):
        self.assertEqual(self.device.firmware_product, "sensor-v1")
        self.assertEqual(self.sensor_firmware.product, "sensor-v1")
