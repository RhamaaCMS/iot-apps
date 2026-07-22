from unittest.mock import AsyncMock, patch

from django.test import TestCase

from ..device_services import create_command, publish_command, set_desired_state
from ..integrations.mqtt import dispatch_one
from ..models import (
    CommandStatus,
    Device,
    DeviceCommand,
    MQTTOutboxMessage,
    Organization,
    OutboxStatus,
)


class CommandOutboxTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Outbox Org")
        self.device = Device.objects.create(organization=self.org, name="Device")

    def test_publish_command_queues_without_marking_sent(self):
        command = create_command(self.device, "reboot")
        publish_command(command)
        command.refresh_from_db()
        self.assertEqual(command.status, CommandStatus.PENDING)
        self.assertEqual(MQTTOutboxMessage.objects.get().reference_id, command.command_id)

    @patch("apps.mqtt.client.mqtt_client.publish", new_callable=AsyncMock)
    def test_dispatch_marks_outbox_and_command_sent(self, publish):
        command = create_command(self.device, "reboot")
        publish_command(command)
        self.assertTrue(dispatch_one())
        command.refresh_from_db()
        self.assertEqual(command.status, CommandStatus.SENT)
        self.assertEqual(MQTTOutboxMessage.objects.get().status, OutboxStatus.SENT)
        publish.assert_awaited_once()

    def test_desired_state_versions_are_monotonic(self):
        first = set_desired_state(self.device, {"relay": True}, publish=False)
        second = set_desired_state(self.device, {"relay": False}, publish=False)
        self.assertEqual((first.desired_version, second.desired_version), (1, 2))
