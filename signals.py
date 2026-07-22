"""
Extensibility hooks for other Django apps (optional use).

from apps.IoT.signals import device_uplink_ingested
device_uplink_ingested.connect(my_handler)
"""

import django.dispatch

device_uplink_ingested = django.dispatch.Signal()
telemetry_recorded = django.dispatch.Signal()
device_state_changed = django.dispatch.Signal()
device_command_changed = django.dispatch.Signal()
