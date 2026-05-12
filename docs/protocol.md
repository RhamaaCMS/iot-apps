# IoT MQTT protocol (v1) — option A

Body format: **MQTT payload = UTF-8 JSON string** (one object per message).

## Envelope (uplink; required fields)

| Field         | Type   | Notes |
|--------------|--------|--------|
| `v`          | int    | Must be `1` (see `ENVELOPE_VERSION` in `constants.py`). |
| `msg_id`     | string | **Strongly recommended** — UUID for deduplication and tracing. |
| `ts`         | string | ISO-8601 UTC, e.g. `2026-04-24T10:00:00.000Z` |
| `org`        | string | **Slug** of the organization (must match the topic segment). |
| `device_id`  | string | **UUID** of the device (must match topic and DB). |
| `channel`    | string | e.g. `telemetry`, `heartbeat`, `status` |
| `schema`     | string | Contract for `data` keys, e.g. `solar_telemetry.v1` (see `ALLOWED_SCHEMAS`). |
| `data`       | object | All sensor / business fields **must** live under `data`. |

## Topic template (uplink, telemetry)

```
iot/v1/{org_slug}/{device_id}/up/telemetry
```

- `org_slug` = `Organization.slug` in the database.  
- `device_id` = `Device.device_id` (UUID string, same as JSON).

You may add other suffixes (e.g. `.../up/heartbeat`) as long as the server subscribes to a matching pattern (e.g. `iot/v1/#`).

## Example: telemetry (uplink)

```json
{
  "v": 1,
  "msg_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "ts": "2026-04-24T10:00:00.000Z",
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

## Evolving `data`

- Never rename keys in an existing `schema` in a breaking way.  
- For new fields or breaking changes, register a **new** `schema` value and add it to `ALLOWED_SCHEMAS` in `apps/IoT/constants.py` when the server should validate it.

## Downlink (server → device)

Use the same envelope and `data` for commands. Topic pattern (suggested):

```
iot/v1/{org_slug}/{device_id}/down/{message_type}
```

(Implementation of publish/ACK is optional in later phases.)

## OTA (firmware over MQTT + HTTPS download)

### Downlink (server → device)

- **Topic:** `iot/v1/{org_slug}/{device_id}/down/ota`  
- **Schema:** `ota_command.v1` (see `OTA_SCHEMA_COMMAND` in `constants.py`).  
- **`data` fields:** `job_id` (UUID string), `product`, `version`, `sha256` (hex), `size` (bytes), `url` (HTTPS GET with signed query `?t=`).

The device fetches the image from `url` (one-time signed token, short TTL, bound to `job_id` and `device_id`). The same public host as used when the server builds the link must be reachable from the device (set `IOT_OTA_PUBLIC_BASE` if the Site domain is wrong).

**Product / SKU:** `data.product` in the command matches `FirmwarePackage.product` in the database. The server only allows pairing when `FirmwarePackage.product` equals **`Device.firmware_product`** (default `default`). Set `firmware_product` on the device Snippet to match your build’s product string.

**Job lifecycle (server):** When a new OTA job is created for a device, any existing job for that device in `pending`, `sent`, or `in_progress` is moved to **`cancelled`** (“superseded by …”). Status uplinks are ignored once a job is **`success`**, **`failed`**, or **`cancelled`** (no duplicate overwrites). If the device missed the MQTT command or the download token expired before fetch, an operator can **republish** a `sent` job from the Wagtail OTA panel (new signed `url`, same `job_id`).

### Uplink (device → server) — OTA status

- **Channel:** `ota`  
- **Schema:** `ota_status.v1` (see `OTA_SCHEMA_STATUS` in `constants.py`).  
- **Topic example:** `iot/v1/{org_slug}/{device_id}/up/ota` (or any `.../up/...` pattern matched by the broker subscription).

**`data` fields (suggested):**

| Field     | Type   | Notes |
|-----------|--------|--------|
| `job_id`  | string | Same UUID as in the command. |
| `phase`   | string | `success` / `failed` / or other in-progress value. |
| `message` | string | Error or progress text (optional). |

**Example (success):**

```json
{
  "v": 1,
  "msg_id": "…",
  "ts": "2026-04-24T10:00:00.000Z",
  "org": "kirei",
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "channel": "ota",
  "schema": "ota_status.v1",
  "data": {
    "job_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    "phase": "success",
    "message": "rebooting"
  }
}
```
