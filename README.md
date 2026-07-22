# IoT App

Multi-tenant connected-device domain for RhamaaCMS `base-iot`. MQTT runtime stays in `apps.mqtt`; this app owns profiles, provisioning, fleet identity, canonical telemetry ingest, state shadow, command lifecycle, audit events, and OTA.

## Connected Device MVP

- `DeviceProfile`: per-tenant product/protocol contract and schema allowlist.
- Provisioning: expiring bootstrap token -> claimed device + one-time plain credential.
- Credentials: hashed at rest, authenticatable, revocable, last-use metadata.
- Telemetry: canonical `TelemetryRecord`, `(device, msg_id)` idempotency, server/device timestamps separated.
- State shadow: desired/reported documents, versions, delta, retained MQTT desired-state downlink.
- Commands: pending/sent/acknowledged/succeeded/failed lifecycle.
- Tenant scope: IoT dashboard/API filtered by `OrganizationMembership`; superusers retain global access.
- Extension signals for InfluxDB and project-specific apps.
- MQTT outbox: database-backed at-least-once downlink delivery with retry and stale-lock recovery.
- Raw Wagtail snippet CRUD/choosers: superuser-only; tenant users use scoped IoT panels.

Provisioning: `POST /IoT/api/v1/provision/` with `{"token":"<id>.<secret>","name":"Device name","hardware_version":"rev1"}`. Returned credential appears once.

Create bootstrap token:

```bash
python manage.py iot_create_provisioning_token --org acme --profile sensor --ttl-minutes 60
```

Schedule `python manage.py iot_expire_commands` periodically to close expired commands.

Run `python manage.py iot_dispatch_outbox --limit 100` continuously or on a short schedule. HTTP/admin requests only enqueue MQTT downlinks; dispatcher performs broker I/O and retry.

> **Note:** Python package is `apps.IoT` (capital `IoT`) — use exactly that in `INSTALLED_APPS` and imports.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  MQTT Broker (e.g., broker.emqx.io)                         │
│  ─ Topics: iot/v1/{org}/{device}/up/telemetry               │
│  ─ Downlink: iot/v1/{org}/{device}/down/ota                 │
└──────────────────────┬──────────────────────────────────────┘
                       │  aiomqtt (async)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  MQTT Client Manager  (apps.mqtt.client)                      │
│  ─ receives messages → signals mqtt_message_received          │
└──────────────────────┬──────────────────────────────────────┘
                       │  Django signals
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  IoT MQTT Handler  (apps.IoT.mqtt_handlers)                 │
│  ─ on_mqtt_incoming → services.process_incoming_mqtt_message│
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  IoT Services  (apps.IoT.services)                          │
│  ─ parse_iot_uplink_topic() → org_slug, device_id           │
│  ─ validate_envelope() → v1 envelope validation             │
│  ─ process_incoming_mqtt_message() → device update + signals  │
│  ─ device_is_online() → last_seen threshold check           │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌─────────────┐
   │ Device  │  │ Device   │  │ OTA Status  │
   │ Update  │  │ Signal   │  │ (ota_services)│
   │ (DB)    │  │ dispatch │  │             │
   └─────────┘  └──────────┘  └─────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Wagtail Admin Dashboards  (apps.IoT.admin_views)           │
│  ─ Ringkasan, Organisasi, Pengguna, Perangkat, OTA          │
│  ─ Secured with @require_admin_access                       │
└─────────────────────────────────────────────────────────────┘
```

---

## File Layout

```
apps/IoT/
├── __init__.py
├── apps.py                  # IotConfig — wires mqtt_message_received signal on ready()
├── models.py                # Organization, OrganizationMembership, Device, FirmwareVersion, DeviceOTAJob
├── services.py              # MQTT envelope validation + device ingest
├── ota_services.py          # OTA jobs: create, publish, republish, status uplink
├── firmware_services.py     # Firmware file validation & helpers
├── mqtt_handlers.py         # Signal receiver: on_mqtt_incoming → services.process_incoming_mqtt_message
├── signals.py               # device_uplink_ingested signal
├── constants.py             # ENVELOPE_VERSION, ALLOWED_SCHEMAS, OTA_* constants, ProtocolSpec
├── admin_views.py           # Wagtail panels: dashboard, orgs, memberships, devices, OTA
├── admin_urls.py            # Routes for admin_views (namespace: iot)
├── admin_snippet_urls.py    # Reverse Wagtail snippet URLs for templates
├── ota_public_views.py      # Signed OTA firmware download (public, no auth)
├── views.py                 # Public placeholder view
├── urls.py                  # Public URL patterns (app_name='IoT')
├── wagtail_hooks.py         # Submenu "IoT" + /admin/iot/ URL registration
├── docs/
│   └── protocol.md          # Human-readable v1 contract for firmware teams
├── rhamaa-app.json          # Machine-readable app manifest
└── templates/IoT/admin/     # Dashboard + panel templates
```

---

## Configuration

### 1. Environment variables

```env
MQTT_BROKER_HOST=broker.emqx.io
MQTT_BROKER_PORT=1883
IOT_OTA_PUBLIC_BASE=https://api.example.com   # Optional; public origin for OTA download URLs
```

`MQTT_BROKER_*` are project-level (see `apps.mqtt`). `IOT_OTA_PUBLIC_BASE` is optional — if unset, `ota_services.get_ota_public_base_url()` falls back to `django.contrib.sites` `Site`, then `http://127.0.0.1:8000` in DEBUG mode.

> Devices must be able to reach the OTA public base host over HTTPS in production.

### 2. Wagtail Settings (runtime)

No dedicated settings model — all configuration is via:
- **Organization** Snippets — tenant slug must match MQTT envelope `org` field
- **Device** Snippets — `device_id` UUID, `firmware_product` for OTA compatibility
- **FirmwareVersion** Snippets — binary upload, product+version unique constraint

---

## Wagtail Admin Dashboards

Access at **Wagtail Admin → IoT** (sidebar submenu with 6 items).

### Ringkasan

Overview dashboard showing:
- Organization count, device count, online count
- Last-seen threshold: devices seen within `ONLINE_THRESHOLD_MINUTES` (default 5 min) are "online"
- Device preview table with online status, last channel, last schema
- Envelope version, allowed schemas, example telemetry topic

### Organisasi

Table of all organizations with:
- Name, slug, active status, device count
- Edit links to the Wagtail Snippet edit page

### Pengguna & organisasi

Table of organization memberships with:
- User, email, organization, role (Admin / Member / Viewer)
- Edit links to the Snippet edit page

### Perangkat

Table of all devices with:
- Name, organization, device_id UUID, firmware_product
- Online/offline status, last seen, last channel/schema
- Edit links + MQTT topic prefix for message filtering

### Firmware Versions

Managed as Wagtail Snippets. Each firmware version includes:
- **Product** SKU (must match `Device.firmware_product`)
- **Version** (semantic, e.g., `1.4.0`)
- **Binary file** (.bin, .elf, .hex, .fw, .img)
- **SHA256** and file size (auto-calculated on save)
- **Hardware compatibility** — min/max hardware version constraints
- **Active** and **Mandatory** flags

### OTA

OTA job management panel:
- **Create job** — select device + firmware, auto-supersedes other in-flight jobs for that device
- **Publish** — sends `ota_command.v1` downlink via MQTT with signed download URL
- **Republish** — re-send for `sent` jobs with a new signed URL
- Job history table with status, device, firmware, downlink topic

**Job lifecycle:** `pending` → `sent` (MQTT published) → `in_progress` (device ack) → `success` / `failed`. Superseded jobs become `cancelled`.

---

## Models

### Organization

Root tenant. `slug` must match the `org` field in the MQTT JSON envelope.

```python
from apps.IoT.models import Organization

org = Organization.objects.create(name="Kirei Solar")
# slug auto-generated from name: "kirei-solar"
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `name` | CharField(255) | Unique case-insensitive |
| `slug` | SlugField(255) | Auto-generated from name; used in MQTT topics |
| `is_active` | BooleanField | Default `True` |
| `created_at` | DateTimeField | Auto-set |

### OrganizationMembership

User ↔ organization access for IoT data and admin.

```python
from apps.IoT.models import OrganizationMembership, MemberRole

OrganizationMembership.objects.create(
    user=request.user,
    organization=org,
    role=MemberRole.ADMIN,
)
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `user` | FK → AUTH_USER_MODEL | |
| `organization` | FK → Organization | |
| `role` | CharField | `admin`, `member`, `viewer` |
| `created_at` | DateTimeField | Auto-set |

### Device

Physical or logical device. `device_id` is the global UUID used in MQTT topics and JSON envelope.

```python
from apps.IoT.models import Device

device = Device.objects.create(
    organization=org,
    name="Panel A1",
    firmware_product="solar-controller-v2",
    hardware_version="rev2",
)
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `organization` | FK → Organization | |
| `name` | CharField(255) | Display name |
| `device_id` | UUIDField | Auto-generated; must match MQTT envelope |
| `is_active` | BooleanField | Default `True` |
| `topic_prefix` | CharField(500) | Optional override for MQTT topic prefix |
| `firmware_product` | CharField(100) | Must match `FirmwareVersion.product` for OTA |
| `hardware_version` | CharField(32) | For firmware compatibility checks |
| `reported_firmware_version` | CharField(100) | Set after successful OTA |
| `last_seen_at` | DateTimeField | Updated on every valid uplink |
| `last_channel` | CharField(100) | Last envelope channel |
| `last_schema` | CharField(200) | Last envelope schema |
| `created_at` | DateTimeField | Auto-set |

### FirmwareVersion

Firmware binary with validation, SHA256, and hardware compatibility.

```python
from apps.IoT.models import FirmwareVersion

fw = FirmwareVersion.objects.create(
    product="solar-controller-v2",
    version="1.4.0",
    file=firmware_binary,
    is_active=True,
    min_hardware_version="rev2",
)
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `product` | CharField(100) | Product SKU / hardware type |
| `version` | CharField(64) | Semantic version |
| `file` | FileField | .bin, .elf, .hex, .fw, .img only |
| `sha256` | CharField(64) | Auto-calculated on save |
| `file_size` | PositiveIntegerField | Auto-calculated on save |
| `is_active` | BooleanField | Only active versions can be deployed |
| `is_mandatory` | BooleanField | Force-update flag |
| `min_hardware_version` | CharField(32) | Optional minimum HW version |
| `max_hardware_version` | CharField(32) | Optional maximum HW version |
| `release_notes` | TextField | |
| `created_at` | DateTimeField | |
| `created_by` | FK → User | Auto-set |

### DeviceOTAJob

One OTA update attempt for a device.

Fields:

| Field | Type | Notes |
|---|---|---|
| `device` | FK → Device | |
| `firmware` | FK → FirmwareVersion | |
| `job_id` | UUIDField | Unique; auto-generated |
| `status` | CharField | `pending`, `sent`, `in_progress`, `success`, `failed`, `cancelled` |
| `error_message` | TextField | Error or progress text from device |
| `created_at` | DateTimeField | |
| `command_sent_at` | DateTimeField | When downlink was published |
| `completed_at` | DateTimeField | When final status received |

---

## Services API

### process_incoming_mqtt_message

Main ingress handler. Called by `mqtt_handlers.on_mqtt_incoming` when an MQTT message arrives.

```python
from apps.IoT.services import process_incoming_mqtt_message

result = process_incoming_mqtt_message(
    topic="iot/v1/kirei/550e8400-e29b-41d4-a716-446655440000/up/telemetry",
    payload='{"v":1,"ts":"2026-05-12T10:00:00Z","org":"kirei","device_id":"550e8400-...","channel":"telemetry","schema":"solar_telemetry.v1","data":{"power_w":4500}}'
)
# Returns: "ok", "skip: not iot/v1", "error: ..."
```

Steps performed:
1. Parse topic → `org_slug`, `device_id`
2. Validate JSON envelope (required keys, version, schema whitelist)
3. Match topic org/device with envelope org/device
4. Look up device by UUID, verify active status
5. If `channel=ota` + `schema=ota_status.v1` → dispatch to `ota_services.apply_ota_status_uplink`
6. Update `Device.last_seen_at`, `last_channel`, `last_schema`
7. Fire `device_uplink_ingested` signal

### validate_envelope

Validate a raw JSON string against the v1 envelope spec.

```python
from apps.IoT.services import validate_envelope

envelope, error = validate_envelope(raw_json_string)
# envelope = parsed dict with "_parsed_ts" datetime
# error = None or validation message
```

### device_is_online

```python
from apps.IoT.services import device_is_online

online = device_is_online(device)
# True if last_seen_at within ONLINE_THRESHOLD_MINUTES (default 5)
```

### recent_mqtt_messages_for_device

Load persisted MQTT messages from `apps.mqtt.models.MQTTMessage` for a device.

```python
from apps.IoT.services import recent_mqtt_messages_for_device

prefix, messages = recent_mqtt_messages_for_device(device, limit=50)
```

---

## OTA Services API

### create_ota_job

Create a new OTA job, superseding any in-flight jobs for the same device.

```python
from apps.IoT.ota_services import create_ota_job

job = create_ota_job(device, firmware)
# Validates: device active, firmware active+hashed, product match, HW version compatible
# Auto-cancels other pending/sent/in_progress jobs for this device
```

### publish_ota_command

Publish the OTA downlink via MQTT. Job must be `pending`.

```python
from apps.IoT.ota_services import publish_ota_command

publish_ota_command(job)
# Builds signed download URL → MQTT publish on iot/v1/{org}/{device}/down/ota
# Updates job status to SENT
```

### republish_ota_command

Re-send the same OTA command with a new signed URL. Job must be `sent`.

```python
from apps.IoT.ota_services import republish_ota_command

republish_ota_command(job)
# Useful when device missed first downlink or token expired
```

### apply_ota_status_uplink

Process `ota_status.v1` uplink from a device. Updates job status and device `reported_firmware_version`.

```python
from apps.IoT.ota_services import apply_ota_status_uplink

apply_ota_status_uplink(device, envelope_dict)
# phase="success" → status=SUCCESS, update reported_firmware_version
# phase="failed" → status=FAILED, store error_message
# other phases → status=IN_PROGRESS
```

---

## MQTT Protocol (v1)

### Uplink Envelope

All MQTT payloads must be UTF-8 JSON objects with these required fields:

| Field | Type | Notes |
|---|---|---|
| `v` | int | Must be `1` (`ENVELOPE_VERSION`) |
| `msg_id` | string | Recommended — UUID for deduplication |
| `ts` | string | ISO-8601 UTC, e.g. `2026-05-12T10:00:00.000Z` |
| `org` | string | Organization slug (must match topic) |
| `device_id` | string | Device UUID (must match topic + DB) |
| `channel` | string | e.g. `telemetry`, `heartbeat`, `ota` |
| `schema` | string | Must satisfy global and device-profile allowlists when configured |
| `data` | object | All business fields under this key |

### Topic Layout

**Uplink:**
```
iot/v1/{org_slug}/{device_id}/up/telemetry
iot/v1/{org_slug}/{device_id}/up/heartbeat
iot/v1/{org_slug}/{device_id}/up/ota
```

**Downlink:**
```
iot/v1/{org_slug}/{device_id}/down/ota
iot/v1/{org_slug}/{device_id}/down/state
iot/v1/{org_slug}/{device_id}/down/command
```

### Allowed Schemas

Global `constants.ALLOWED_SCHEMAS` is empty by default. Define reusable protocol contracts per `DeviceProfile.allowed_schemas`; an empty profile list accepts any valid schema.

### Example Telemetry Uplink

```json
{
  "v": 1,
  "msg_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "ts": "2026-05-12T10:00:00.000Z",
  "org": "kirei",
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "channel": "telemetry",
  "schema": "solar_telemetry.v1",
  "data": {
    "power_w": 4500,
    "voltage_v": 230.5
  }
}
```

For the full protocol contract, see `apps/IoT/docs/protocol.md`.

---

## Admin API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/admin/iot/` | GET | Dashboard (Ringkasan) |
| `/admin/iot/organizations/` | GET | Organization panel |
| `/admin/iot/memberships/` | GET | Membership panel |
| `/admin/iot/devices/` | GET | Device panel |
| `/admin/iot/ota/` | GET / POST | OTA panel; POST actions: `create`, `publish`, `republish` |
| `/admin/iot/api/mqtt-bridge-status/` | GET | MQTT connection + active topics |
| `/admin/iot/api/devices/` | GET | JSON device summary (online/offline) |
| `/admin/iot/api/devices/<pk>/mqtt-messages/?limit=N` | GET | Recent MQTT messages for device |
| `/admin/iot/api/envelope-preview/` | POST | Validate raw envelope JSON |

All endpoints require Wagtail staff access (`@require_admin_access`).

---

## Public OTA Download

Devices fetch firmware via signed URL (no browser auth):

```
GET /ota/firmware/?t=<signed-token>
```

- Token is signed with `django.core.signing` (`OTA_DOWNLOAD_SALT`)
- Valid for 7 days, bound to `job_id` + `device_id`
- Job must be in `pending`, `sent`, or `in_progress` status
- Returns firmware binary as `FileResponse` with `Content-Disposition: attachment`

**Important:** Register this route at the **project level** (`solar_monitoring_apps/urls.py`), not in the app’s `urls.py`:

```python
from apps.IoT.ota_public_views import ota_public_download

urlpatterns = [
    path("ota/firmware/", ota_public_download),
    # ... other routes
]
```

---

## Dependencies

| App / Package | Purpose |
|---|---|
| `apps.mqtt` | MQTT client, message persistence, signals |
| `wagtail.snippets` | Organization, Device, FirmwareVersion, OTAJob as Snippets |
| `django.core.signing` | Signed OTA download tokens |

---

## Development Tips

- **App label is lowercase `iot`** — use `python manage.py migrate iot` (but `INSTALLED_APPS` uses `apps.IoT`).
- **MQTT integration** is via signal (`mqtt_message_received`) → `mqtt_handlers.on_mqtt_incoming`. No direct coupling to `apps.mqtt.client` in `services.py`.
- **Envelope validation** is strict — missing keys, wrong version, unknown schema, or topic/envelope mismatch all return error strings and skip processing.
- **OTA superseding** — creating a new OTA job for a device automatically cancels older pending/sent/in-progress jobs.
- **Republish** — only `sent` jobs can be republished. Creates a fresh signed URL without changing `job_id`.
- **Firmware file validation** — max size `OTA_MAX_FIRMWARE_BYTES` (16 MB), allowed extensions: `.bin`, `.elf`, `.hex`, `.fw`, `.img`.
- **Hardware compatibility** — `FirmwareVersion.min/max_hardware_version` filters which firmware a device can receive.
- **Online threshold** — 5 minutes (`ONLINE_THRESHOLD_MINUTES`). Change in `constants.py` if needed.

---

## License

MIT
