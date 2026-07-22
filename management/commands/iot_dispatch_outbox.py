from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Compatibility alias for the dedicated base-iot mqtt_worker."

    def handle(self, **options):
        self.stdout.write(
            self.style.WARNING("iot_dispatch_outbox is deprecated; starting mqtt_worker.")
        )
        call_command("mqtt_worker")
