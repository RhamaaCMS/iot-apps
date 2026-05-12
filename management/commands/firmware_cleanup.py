"""
Management command for firmware file cleanup and maintenance.

Usage:
    python manage.py firmware_cleanup --dry-run          # Preview orphaned files
    python manage.py firmware_cleanup                   # Actually delete orphaned files
    python manage.py firmware_cleanup --stats           # Show storage statistics
    python manage.py firmware_cleanup --list-folders    # List all firmware folders
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.IoT import firmware_services


class Command(BaseCommand):
    help = "Firmware file cleanup and storage management"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--stats",
            action="store_true",
            help="Show storage statistics only",
        )
        parser.add_argument(
            "--list-folders",
            action="store_true",
            help="List all firmware folders",
        )
        parser.add_argument(
            "--validate",
            action="store_true",
            help="Validate all firmware files exist in storage",
        )

    def handle(self, *args, **options):
        if options["stats"]:
            self.show_stats()
            return

        if options["list_folders"]:
            self.list_folders()
            return

        if options["validate"]:
            self.validate_files()
            return

        # Default: cleanup orphaned files
        self.cleanup_orphaned(options["dry_run"])

    def show_stats(self):
        """Display storage statistics."""
        stats = firmware_services.get_storage_stats()

        self.stdout.write(self.style.MIGRATE_HEADING("Firmware Storage Statistics"))
        self.stdout.write("=" * 50)
        self.stdout.write(f"Total folders:    {stats['total_folders']}")
        self.stdout.write(f"Total files:      {stats['total_files']}")
        self.stdout.write(f"Total size:       {stats['total_size_human']}")
        self.stdout.write(f"Unique products:  {stats['unique_products']}")
        self.stdout.write(f"Unique versions:  {stats['unique_versions']}")

        if stats["products"]:
            self.stdout.write("\nProducts:")
            for product in stats["products"]:
                self.stdout.write(f"  - {product}")

    def list_folders(self):
        """List all firmware folders."""
        folders = firmware_services.list_firmware_folders()

        self.stdout.write(self.style.MIGRATE_HEADING("Firmware Folders"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"{'Product':<20} {'Version':<15} {'Files':>8} {'Size':>12}")
        self.stdout.write("-" * 70)

        for folder in folders:
            self.stdout.write(
                f"{folder['product']:<20} {folder['version']:<15} "
                f"{folder['file_count']:>8} {folder['total_size_human']:>12}"
            )

    def validate_files(self):
        """Validate all firmware files exist in storage."""
        from apps.IoT.models import FirmwareVersion

        self.stdout.write(self.style.MIGRATE_HEADING("Validating Firmware Files"))

        firmwares = FirmwareVersion.objects.all()
        missing = []
        valid = 0

        for fw in firmwares:
            exists = firmware_services.validate_file_exists(fw)
            if not exists:
                missing.append({
                    "id": fw.id,
                    "product": fw.product,
                    "version": fw.version,
                    "path": fw.storage_path,
                })
                self.stdout.write(
                    self.style.ERROR(f"MISSING: {fw} at {fw.storage_path}")
                )
            else:
                valid += 1

        self.stdout.write(f"\n{'='*50}")
        self.stdout.write(f"Valid files:   {valid}")
        self.stdout.write(f"Missing files: {len(missing)}")

        if missing:
            self.stdout.write(self.style.WARNING("\nConsider running cleanup or re-uploading missing files."))

    def cleanup_orphaned(self, dry_run: bool):
        """Cleanup orphaned firmware folders."""
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Firmware Cleanup {'(DRY RUN)' if dry_run else '(LIVE)'}"
            )
        )

        actions = firmware_services.cleanup_orphaned_folders(dry_run=dry_run)

        if not actions:
            self.stdout.write(self.style.SUCCESS("No orphaned folders found."))
            return

        self.stdout.write(f"\nFound {len(actions)} orphaned folder(s):\n")
        self.stdout.write(f"{'Path':<40} {'Files':>8} {'Action':>15}")
        self.stdout.write("-" * 70)

        for action in actions:
            path = f"{action['product']}/{action['version']}"[:38]
            self.stdout.write(
                f"{path:<40} {action['file_count']:>8} {action['action']:>15}"
            )

        if dry_run:
            self.stdout.write(
                self.style.NOTICE("\nThis was a dry run. Use without --dry-run to actually delete.")
            )
        else:
            successful = sum(1 for a in actions if a.get("success", False))
            self.stdout.write(
                self.style.SUCCESS(f"\nDeleted {successful}/{len(actions)} folders.")
            )
