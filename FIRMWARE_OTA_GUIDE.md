# Firmware OTA System Guide

Sistem OTA (Over-The-Air) yang solid untuk mengelola firmware perangkat IoT dengan struktur folder terorganisir.

## Fitur Baru

### 1. FirmwareVersion Snippet
Model `FirmwareVersion` menggantikan `FirmwarePackage` dengan fitur tambahan:

- **Struktur Folder Terisolasi**: Setiap versi disimpan di folder tersendiri
  - Pattern: `iot/firmware/{product}/{version}/{hash}_{filename}`
  - Contoh: `iot/firmware/solar-controller/1-4-0/a1b2c3d4_firmware.bin`

- **Hardware Compatibility**: Validasi hardware version perangkat
  - `min_hardware_version`: Minimum hardware yang didukung
  - `max_hardware_version`: Maximum hardware yang didukung

- **Mandatory Updates**: Tandai versi sebagai wajib diupdate

- **Metadata Lengkap**: SHA256 hash, file size, release notes

### 2. Device Hardware Version
Field baru di model `Device`:
- `hardware_version`: Hardware revision perangkat (e.g., "rev2", "v1.1")
- Digunakan untuk validasi kompatibilitas firmware

## Struktur Storage

```
media/
└── iot/
    └── firmware/
        ├── solar-controller-v2/
        │   ├── 1-4-0/
        │   │   └── a1b2c3d4_firmware.bin
        │   ├── 2-0-0-beta1/
        │   │   └── e5f6g7h8_firmware.bin
        │   └── 2-0-0/
        │       └── i9j0k1l2_firmware.bin
        └── solar-monitor-v1/
            ├── 1-0-0/
            │   └── m3n4o5p6_firmware.bin
            └── 1-1-0/
                └── q7r8s9t0_firmware.bin
```

Keunggulan:
- **No Overwrites**: Setiap versi punya folder sendiri
- **Easy Backup**: Backup per product/version
- **Clean Management**: Hapus versi = hapus folder

## Usage

### Upload Firmware Version

1. Buka Wagtail Admin → IoT → Firmware Versions
2. Klik "Add Firmware Version"
3. Isi:
   - **Product**: SKU hardware (e.g., "solar-controller-v2")
   - **Version**: Semantic version (e.g., "1.4.0")
   - **File**: Binary firmware (.bin, .elf, .hex)
   - **Hardware Compatibility** (optional)
   - **Release Notes** (optional)
   - **Mandatory**: Check jika update wajib
   - **Active**: Check untuk mengaktifkan

### Create OTA Job

```python
from apps.IoT.models import Device, FirmwareVersion
from apps.IoT.ota_services import create_ota_job, publish_ota_command

# Get device and firmware
device = Device.objects.get(device_id="...")
firmware = FirmwareVersion.objects.get(product="solar-controller-v2", version="1.4.0")

# Create job
job = create_ota_job(device, firmware)

# Publish via MQTT
publish_ota_command(job)
```

### Check Compatible Firmware

```python
from apps.IoT.ota_services import get_compatible_firmware_for_device

# Get all compatible firmware for a device
compatible = get_compatible_firmware_for_device(device)

# Get only mandatory updates
mandatory = get_compatible_firmware_for_device(device, include_mandatory_only=True)
```

### File Management Utilities

```python
from apps.IoT import firmware_services

# List all firmware folders
folders = firmware_services.list_firmware_folders()

# Get storage stats
stats = firmware_services.get_storage_stats()
print(f"Total size: {stats['total_size_human']}")

# Validate files exist
is_valid = firmware_services.validate_file_exists(firmware)

# Cleanup orphaned folders (dry run)
orphaned = firmware_services.cleanup_orphaned_folders(dry_run=True)

# Duplicate a version
new_fw = firmware_services.duplicate_firmware_version(source_fw, "1.4.1-beta")
```

## Management Commands

### View Statistics
```bash
python manage.py firmware_cleanup --stats
```

Output:
```
Firmware Storage Statistics
==================================================
Total folders:    5
Total files:      5
Total size:       2.5 MB
Unique products:  2
Unique versions:  5
```

### List All Folders
```bash
python manage.py firmware_cleanup --list-folders
```

### Validate Files
```bash
python manage.py firmware_cleanup --validate
```

### Cleanup Orphaned Files (Preview)
```bash
python manage.py firmware_cleanup --dry-run
```

### Cleanup Orphaned Files (Execute)
```bash
python manage.py firmware_cleanup
```

## OTA Flow

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Device    │     │   Django Server │     │   Storage   │
└──────┬──────┘     └────────┬────────┘     └──────┬──────┘
       │                     │                      │
       │ 1. Report version   │                      │
       │────────────────────>│                      │
       │                     │                      │
       │                     │ 2. Check compatible   │
       │                     │─────────────────────>│
       │                     │                      │
       │ 3. Create OTA job   │                      │
       │<────────────────────│                      │
       │                     │                      │
       │ 4. OTA command (MQTT)                     │
       │<────────────────────│                      │
       │    (signed URL)     │                      │
       │                     │                      │
       │ 5. Download request │                      │
       │────────────────────>│                      │
       │                     │ 6. Validate & serve  │
       │                     │─────────────────────>│
       │                     │                      │
       │ 7. Firmware binary  │                      │
       │<────────────────────│                      │
       │                     │                      │
       │ 8. Status uplink    │                      │
       │────────────────────>│                      │
       │                     │                      │
```

## API Endpoints

### Public OTA Download
```
GET /ota/firmware/?t=<signed_token>
```
- Token signed dengan salt `iot-ota-firmware-v1`
- Valid 7 hari
- Device-specific (hanya device yang dituju bisa download)

## Backward Compatibility

- `FirmwarePackage` adalah alias untuk `FirmwareVersion`
- Semua kode lama tetap berfungsi
- Migration otomatis akan:
  1. Membuat tabel `FirmwareVersion` baru
  2. Memindahkan data dari `FirmwarePackage`
  3. Menghapus tabel `FirmwarePackage` lama

## Security

1. **Signed URLs**: Download link menggunakan Django signing
2. **Device-specific**: Token berisi job_id dan device_id
3. **File validation**: SHA256 hash dicek sebelum OTA
4. **Storage isolation**: Folder per versi mencegah file confusion

## Troubleshooting

### File Not Found Error
```bash
# Validate semua firmware
python manage.py firmware_cleanup --validate
```

### Storage Penuh
```bash
# Cleanup file yang tidak terpakai
python manage.py firmware_cleanup --dry-run
python manage.py firmware_cleanup
```

### Hardware Compatibility Error
Pastikan:
1. Device memiliki `hardware_version` yang benar
2. Firmware memiliki `min/max_hardware_version` yang sesuai

### Migration Error
Jika ada error saat migration:
```bash
# Backup database dulu
cp db.sqlite3 db.sqlite3.backup

# Run migration
python manage.py migrate iot
```
