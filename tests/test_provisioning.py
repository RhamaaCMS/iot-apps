import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from ..device_services import authenticate_device, claim_device, create_provisioning_token
from ..models import Device, DeviceProfile, Organization


class ProvisioningTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Factory")
        self.profile = DeviceProfile.objects.create(
            organization=self.org, name="Gateway", slug="gateway", product_code="gw-v1"
        )

    def test_token_claim_returns_non_persisted_plain_credential(self):
        token, raw = create_provisioning_token(
            self.org, self.profile, ttl=timedelta(minutes=5)
        )
        device, credential = claim_device(raw, name="Gateway 1")
        token.refresh_from_db()
        self.assertFalse(token.is_active)
        self.assertEqual(device.firmware_product, "gw-v1")
        self.assertEqual(authenticate_device(credential), device)
        self.assertNotIn(credential.split(".", 1)[1], device.credentials.get().secret_hash)

    def test_consumed_token_cannot_claim_again(self):
        _, raw = create_provisioning_token(self.org, self.profile)
        claim_device(raw, name="One")
        with self.assertRaisesMessage(ValidationError, "expired, exhausted, or invalid"):
            claim_device(raw, name="Two")

    def test_http_provision_rejects_foreign_app_id_before_claim(self):
        _, raw = create_provisioning_token(self.org, self.profile)
        response = self.client.post(
            reverse("IoT:provision"),
            data=json.dumps({"app_id": "foreign-app", "token": raw, "name": "Foreign"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Device.objects.count(), 0)
