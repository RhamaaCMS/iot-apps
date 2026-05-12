"""
IoT MQTT / envelope constants — single place for protocol version and topic rules.
"""

# Topic layout: {prefix}/{org_slug}/{device_id}/up/telemetry
# (channel is always present in the JSON envelope; use .../up for generic uplink if needed)
IOT_MQTT_TOPIC_PREFIX = "iot/v1"

# Envelope field "v" must match for strict validation
ENVELOPE_VERSION = 1

# Devices with last_seen within this window are shown as "online" in the admin dashboard
ONLINE_THRESHOLD_MINUTES = 5

# If non-empty, incoming messages must use one of these schema strings in the envelope
ALLOWED_SCHEMAS = frozenset(
    {
        "solar_telemetry.v1",
        "heartbeat.v1",
        "ota_status.v1",
    }
)

# OTA (downlink uses same envelope; not validated against ALLOWED_SCHEMAS on publish)
OTA_CHANNEL = "ota"
OTA_SCHEMA_COMMAND = "ota_command.v1"
OTA_SCHEMA_STATUS = "ota_status.v1"
# Signed download token lifetime (used by django.core.signing)
OTA_DOWNLOAD_SALT = "iot-ota-firmware-v1"
# Optional max firmware size in bytes (validator on model)
OTA_MAX_FIRMWARE_BYTES = 16 * 1024 * 1024


class ProtocolSpec:
    """
    Machine-readable contract for the global envelope (option A: payload in "data").

    Reference copy lives in apps/IoT/docs/protocol.md for firmware and backend teams.
    """

    REQUIRED_ENVELOPE_KEYS = (
        "v",
        "ts",
        "org",
        "device_id",
        "channel",
        "schema",
        "data",
    )
    OPTIONAL_ENVELOPE_KEYS = ("msg_id",)
    DATA_KEY = "data"
