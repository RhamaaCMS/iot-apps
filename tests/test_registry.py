import json

from django.test import TestCase
from django.urls import reverse

from ..device_services import authenticate_device, create_provisioning_token
from ..models import Device, DeviceProfile, Organization


class DeviceAutoRegistryTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Auto Factory")
        _, self.raw_token = create_provisioning_token(
            self.organization, None, max_claims=2
        )
        self.sample = {"temperature_c": 27.4, "relay": True, "label": "zone-a"}

    def register(self, mac, secret):
        return self.client.post(
            reverse("IoT:registry"),
            data=json.dumps({
                "app_id": "iot-dev-local",
                "token": self.raw_token,
                "credential_secret": secret,
                "hardware_id": mac,
                "name": f"Sensor {mac}",
                "hardware_version": "rev1",
                "firmware_product": "environment-sensor",
                "firmware_version": "0.3.0",
                "schema": "environment_telemetry.v1",
                "sample_data": self.sample,
            }),
            content_type="application/json",
        )

    def test_one_call_creates_profile_device_and_credential_from_mac(self):
        response = self.register("AA:BB:CC:11:22:33", "first-device-secret-with-enough-entropy")
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["device_id"], "AABBCC112233")
        device = Device.objects.get(device_id="AABBCC112233")
        self.assertEqual(device.profile.schema_contracts["environment_telemetry.v1"], {
            "label": "string", "relay": "boolean", "temperature_c": "number"
        })
        self.assertEqual(authenticate_device(payload["credential"]), device)

    def test_same_shape_reuses_profile_and_retry_is_idempotent(self):
        first_secret = "first-device-secret-with-enough-entropy"
        self.assertEqual(self.register("AABBCC112233", first_secret).status_code, 201)
        retry = self.register("AA-BB-CC-11-22-33", first_secret)
        self.assertEqual(retry.status_code, 200)
        self.assertFalse(retry.json()["created"])

        second = self.register("AABBCC445566", "second-device-secret-with-enough-entropy")
        self.assertEqual(second.status_code, 201)
        self.assertEqual(Device.objects.count(), 2)
        self.assertEqual(DeviceProfile.objects.count(), 1)

    def test_invalid_or_duplicate_mac_identity_is_rejected(self):
        invalid = self.register("ESP32-NOT-A-MAC", "invalid-device-secret-with-enough-entropy")
        self.assertEqual(invalid.status_code, 403)
        secret = "first-device-secret-with-enough-entropy"
        self.register("AABBCC112233", secret)
        conflict = self.register("AABBCC112233", "different-device-secret-with-enough-entropy")
        self.assertEqual(conflict.status_code, 403)
