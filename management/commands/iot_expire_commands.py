from django.core.management.base import BaseCommand
from django.utils import timezone

from ...models import CommandStatus, DeviceCommand


class Command(BaseCommand):
    help = "Mark expired pending/sent/acknowledged device commands as timed out."

    def handle(self, **options):
        count = DeviceCommand.objects.filter(
            status__in=(CommandStatus.PENDING, CommandStatus.SENT, CommandStatus.ACKNOWLEDGED),
            expires_at__lt=timezone.now(),
        ).update(status=CommandStatus.TIMED_OUT, completed_at=timezone.now())
        self.stdout.write(str(count))
