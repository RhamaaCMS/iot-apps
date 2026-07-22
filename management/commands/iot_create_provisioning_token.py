from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from ...device_services import create_provisioning_token
from ...models import DeviceProfile, Organization


class Command(BaseCommand):
    help = "Create a bootstrap token. Plain token is printed once."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="Organization slug")
        parser.add_argument("--profile", required=True, help="DeviceProfile slug")
        parser.add_argument("--ttl-minutes", type=int, default=60)
        parser.add_argument("--max-claims", type=int, default=1)
        parser.add_argument("--label", default="")

    def handle(self, **options):
        try:
            organization = Organization.objects.get(slug=options["org"], is_active=True)
            profile = DeviceProfile.objects.get(
                organization=organization, slug=options["profile"], is_active=True
            )
            _, raw_token = create_provisioning_token(
                organization,
                profile,
                label=options["label"],
                ttl=timedelta(minutes=options["ttl_minutes"]),
                max_claims=options["max_claims"],
            )
        except (Organization.DoesNotExist, DeviceProfile.DoesNotExist) as exc:
            raise CommandError("Active organization/profile not found.") from exc
        self.stdout.write(raw_token)
