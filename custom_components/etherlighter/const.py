"""Constants for the Etherlighter integration."""

from __future__ import annotations

DOMAIN = "etherlighter"

DEFAULT_NAME = "Etherlighter"
DEFAULT_PORT = 22
DEFAULT_CYCLE_INTERVAL = 0.2
DEFAULT_CYCLE_BRIGHTNESS = 100
DEFAULT_CYCLE_STEPS = 96

CONF_HOST_KEY_FINGERPRINT = "host_key_fingerprint"

ATTR_MODE = "mode"
ATTR_PATTERN = "pattern"
ATTR_INTERVAL = "interval"
ATTR_BRIGHTNESS = "brightness"

SERVICE_SET_MODE = "set_mode"
SERVICE_START_CYCLE = "start_cycle"
SERVICE_STOP_CYCLE = "stop_cycle"

CYCLE_PATTERN_ALL = "all"
CYCLE_PATTERN_OFFSET = "offset"
CYCLE_PATTERNS = (CYCLE_PATTERN_ALL, CYCLE_PATTERN_OFFSET)

MODE_NETWORK = "network"
MODE_COMMANDS = {
    "cold_reset": ("0",),
    "warm_reset": ("1",),
    "boot_done": ("2",),
    "speed": ("10", "0"),
    MODE_NETWORK: ("10", "1"),
    "poe": ("10", "2"),
    "device_type": ("10", "3"),
    "port_locate": ("10", "4"),
    "port_locate_unset": ("10", "5"),
}

MODE_LABELS = {
    MODE_NETWORK: "Network",
    "speed": "Speed",
    "poe": "PoE",
    "device_type": "Device Type",
    "cold_reset": "Cold Reset",
    "warm_reset": "Warm Reset",
    "boot_done": "Boot Done",
    "port_locate": "Port Locate",
    "port_locate_unset": "Port Locate Unset",
}

MODE_KEYS = tuple(MODE_LABELS)
MODE_KEY_BY_LABEL = {label: key for key, label in MODE_LABELS.items()}
