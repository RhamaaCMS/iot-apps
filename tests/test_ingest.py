import json

from django.test import TestCase
from django.utils import timezone

from ..models import Device, DeviceProfile, Organization, TelemetryRecord
from ..services import process_incoming_mqtt_message


class IoTIngestTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.profile = DeviceProfile.objects.create(
            organization=self.org,
            name="Sensor",
            slug="sensor",
            allowed_schemas=["temperature.v1", "device_state.v1"],
        )
        self.device = Device.objects.create(
            organization=self.org, profile=self.profile, name="Sensor 1"
        )

    def envelope(self, **changes):
        body = {
            "v": 1,
            "ts": "2026-01-01T00:00:00Z",
            "org": self.org.slug,
            "device_id": str(self.device.device_id),
            "channel": "telemetry",
            "schema": "temperature.v1",
            "msg_id": "message-1",
            "data": {"temperature": 24.5},
        }
        body.update(changes)
        return json.dumps(body)

    @property
    def topic(self):
        return f"iot/v1/{self.org.slug}/{self.device.device_id}/up/telemetry"

    def test_ingest_uses_server_time_and_keeps_device_time(self):
        before = timezone.now()
        self.assertEqual(process_incoming_mqtt_message(self.topic, self.envelope()), "ok")
        self.device.refresh_from_db()
        self.assertGreaterEqual(self.device.last_seen_at, before)
        self.assertEqual(self.device.last_device_timestamp.isoformat(), "2026-01-01T00:00:00+00:00")
        self.assertEqual(TelemetryRecord.objects.get().payload["temperature"], 24.5)

    def test_duplicate_message_id_is_idempotent(self):
        self.assertEqual(process_incoming_mqtt_message(self.topic, self.envelope()), "ok")
        self.assertEqual(process_incoming_mqtt_message(self.topic, self.envelope()), "skip: duplicate msg_id")
        self.assertEqual(TelemetryRecord.objects.count(), 1)

    def test_profile_rejects_unknown_schema(self):
        result = process_incoming_mqtt_message(self.topic, self.envelope(schema="unknown.v1"))
        self.assertEqual(result, "error: schema not allowed by device profile")
        self.assertFalse(TelemetryRecord.objects.exists())
