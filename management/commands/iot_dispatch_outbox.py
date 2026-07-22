from django.core.management.base import BaseCommand

from ...integrations.mqtt import dispatch_one, recover_stale


class Command(BaseCommand):
    help = "Dispatch queued IoT MQTT messages with retry."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, **options):
        recover_stale()
        processed = 0
        for _ in range(max(0, options["limit"])):
            if not dispatch_one():
                break
            processed += 1
        self.stdout.write(str(processed))
