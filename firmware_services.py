"""
Firmware file management services — storage utilities, cleanup, and version helpers.

Import from other apps as:
    from apps.IoT import firmware_services
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models import QuerySet

if TYPE_CHECKING:
    from .models import FirmwareVersion


def get_firmware_storage_path(product: str, version: str, filename: str) -> str:
    """
    Generate storage path for a firmware file.
    Pattern: iot/firmware/{product_slug}/{version}/{filename}
    """
    from django.utils.text import slugify
    import hashlib
    import time

    product_slug = slugify(product) or "default"
    version_slug = slugify(version) or "unknown"

    # Add hash prefix for uniqueness
    hash_prefix = hashlib.md5(f"{product}:{version}:{time.time()}".encode()).hexdigest()[:8]
    safe_filename = os.path.basename(filename).replace(" ", "_")

    return f"iot/firmware/{product_slug}/{version_slug}/{hash_prefix}_{safe_filename}"


def list_firmware_folders() -> list[dict]:
    """
    List all firmware storage folders with file counts and sizes.
    Returns list of dicts with: product, version, path, file_count, total_size
    """
    from django.core.files.storage import default_storage

    base_path = "iot/firmware"
    folders = []

    try:
        # Try to list products
        _, products = default_storage.listdir(base_path)
    except (OSError, FileNotFoundError):
        return folders

    for product in products:
        product_path = f"{base_path}/{product}"
        try:
            _, versions = default_storage.listdir(product_path)
        except (OSError, FileNotFoundError):
            continue

        for version in versions:
            version_path = f"{product_path}/{version}"
            try:
                files, _ = default_storage.listdir(version_path)
            except (OSError, FileNotFoundError):
                continue

            # Calculate total size
            total_size = 0
            for f in files:
                try:
                    file_path = f"{version_path}/{f}"
                    total_size += default_storage.size(file_path)
                except (OSError, FileNotFoundError):
                    pass

            folders.append({
                "product": product,
                "version": version,
                "path": version_path,
                "file_count": len(files),
                "total_size": total_size,
                "total_size_human": _human_readable_size(total_size),
            })

    return sorted(folders, key=lambda x: (x["product"], x["version"]))


def cleanup_orphaned_folders(dry_run: bool = True) -> list[dict]:
    """
    Find and optionally remove orphaned firmware folders (no matching FirmwareVersion record).

    Args:
        dry_run: If True, only report what would be deleted without actually deleting.

    Returns:
        List of actions taken (or planned if dry_run=True).
    """
    from .models import FirmwareVersion

    actions = []
    folders = list_firmware_folders()

    # Get all active firmware records with their storage paths
    active_records = FirmwareVersion.objects.all()
    active_paths = set()
    for fw in active_records:
        if fw.storage_path:
            # Get just the directory part
            path_parts = fw.storage_path.split("/")
            if len(path_parts) >= 4:
                folder_path = "/".join(path_parts[:4])  # iot/firmware/product/version
                active_paths.add(folder_path)

    for folder in folders:
        folder_path = folder["path"]

        # Check if this folder is referenced by any active firmware
        is_orphaned = True
        for active_path in active_paths:
            if folder_path.startswith(active_path) or active_path.startswith(folder_path):
                is_orphaned = False
                break

        if is_orphaned:
            action = {
                "path": folder_path,
                "product": folder["product"],
                "version": folder["version"],
                "file_count": folder["file_count"],
                "size": folder["total_size_human"],
                "action": "would_delete" if dry_run else "deleted",
            }

            if not dry_run:
                try:
                    _delete_folder_recursive(folder_path)
                    action["success"] = True
                except Exception as e:
                    action["success"] = False
                    action["error"] = str(e)

            actions.append(action)

    return actions


def get_storage_stats() -> dict:
    """
    Get overall firmware storage statistics.
    """
    folders = list_firmware_folders()

    total_size = sum(f["total_size"] for f in folders)
    total_files = sum(f["file_count"] for f in folders)
    products = set(f["product"] for f in folders)
    versions = set(f"{f['product']}/{f['version']}" for f in folders)

    return {
        "total_folders": len(folders),
        "total_files": total_files,
        "total_size": total_size,
        "total_size_human": _human_readable_size(total_size),
        "unique_products": len(products),
        "unique_versions": len(versions),
        "products": sorted(products),
    }


def validate_file_exists(firmware: "FirmwareVersion") -> bool:
    """
    Check if the firmware file actually exists in storage.
    """
    if not firmware.file or not firmware.file.name:
        return False

    try:
        return default_storage.exists(firmware.file.name)
    except Exception:
        return False


def get_version_folder_path(firmware: "FirmwareVersion") -> str | None:
    """
    Get the folder path for a firmware version.
    Returns path like: iot/firmware/{product}/{version}/
    """
    if not firmware.file or not firmware.file.name:
        return None

    parts = firmware.file.name.split("/")
    if len(parts) >= 4:
        return "/".join(parts[:4])  # iot/firmware/product/version
    return None


def duplicate_firmware_version(source: "FirmwareVersion", new_version: str) -> "FirmwareVersion":
    """
    Duplicate an existing firmware version with a new version string.
    Creates a copy of the file in a new folder.
    """
    from .models import FirmwareVersion
    import shutil
    from django.core.files.base import ContentFile

    if not source.file:
        raise ValueError("Source firmware has no file")

    # Create new firmware record
    new_fw = FirmwareVersion(
        product=source.product,
        version=new_version,
        is_active=False,  # Default to inactive, admin must activate
        is_mandatory=False,
        release_notes=f"Duplicated from {source.version}\n\n{source.release_notes}",
        min_hardware_version=source.min_hardware_version,
        max_hardware_version=source.max_hardware_version,
    )

    # Read source file content
    try:
        source.file.open("rb")
        file_content = source.file.read()
        source.file.seek(0)
    except Exception as e:
        raise ValueError(f"Could not read source file: {e}")

    # Get original filename
    original_name = os.path.basename(source.file.name)

    # Save new firmware (this will handle the upload path and hash calculation)
    new_fw.file.save(original_name, ContentFile(file_content), save=False)
    new_fw.save()

    return new_fw


# Helper functions


def _human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _delete_folder_recursive(path: str) -> None:
    """Recursively delete a folder and all its contents from storage."""
    from django.core.files.storage import default_storage

    try:
        files, dirs = default_storage.listdir(path)
    except (OSError, FileNotFoundError):
        return

    # Delete files first
    for f in files:
        try:
            default_storage.delete(f"{path}/{f}")
        except Exception:
            pass

    # Delete subdirectories (recursively)
    for d in dirs:
        _delete_folder_recursive(f"{path}/{d}")

    # Try to delete the folder itself (if storage backend supports it)
    try:
        default_storage.delete(path)
    except Exception:
        pass


# Import aliased to main models for convenience
def get_compatible_firmware_versions(device) -> QuerySet:
    """
    Get all firmware versions compatible with a given device.
    Filters by: product, is_active=True, hardware version constraints.
    """
    from .models import FirmwareVersion

    dev_product = (device.firmware_product or "").strip() or "default"
    hw_version = getattr(device, "hardware_version", "")

    qs = FirmwareVersion.objects.filter(
        product=dev_product,
        is_active=True,
    ).order_by("-created_at")

    # Filter by hardware version if set
    if hw_version:
        # This is a simplified filter - in practice you might want more complex logic
        # for hardware version comparison
        from django.db.models import Q
        qs = qs.filter(
            Q(min_hardware_version="") | Q(min_hardware_version__lte=hw_version)
        ).filter(
            Q(max_hardware_version="") | Q(max_hardware_version__gte=hw_version)
        )

    return qs


def get_latest_firmware_version(device, include_inactive: bool = False) -> "FirmwareVersion | None":
    """
    Get the latest firmware version for a device.
    Returns the most recently created compatible version, or None if none found.
    """
    qs = get_compatible_firmware_versions(device)
    if include_inactive:
        from .models import FirmwareVersion
        dev_product = (device.firmware_product or "").strip() or "default"
        qs = FirmwareVersion.objects.filter(product=dev_product).order_by("-created_at")

    return qs.first()
