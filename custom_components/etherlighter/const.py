"""Constants for the Etherlighter integration."""

from __future__ import annotations

DOMAIN = "etherlighter"

DEFAULT_NAME = "Etherlighter"
DEFAULT_PORT = 22
DEFAULT_CYCLE_INTERVAL = 0.2
DEFAULT_CYCLE_BRIGHTNESS = 100
DEFAULT_CYCLE_STEPS = 96
DEFAULT_TRANSITION_SPEED = 50
DEFAULT_SCANNER_TAIL = 4

CONF_HOST_KEY_FINGERPRINT = "host_key_fingerprint"

ATTR_MODE = "mode"
ATTR_PATTERN = "pattern"
ATTR_INTERVAL = "interval"
ATTR_BRIGHTNESS = "brightness"

SERVICE_SET_MODE = "set_mode"
SERVICE_START_CYCLE = "start_cycle"
SERVICE_STOP_CYCLE = "stop_cycle"

CYCLE_PATTERN_ALL = "all"
CYCLE_PATTERN_KITT = "kitt"
CYCLE_PATTERN_OFFSET = "offset"
# KITT is implemented in the engine but disabled in the UI for now: its
# host-driven per-frame SSH writes stutter. Keep it out of the exposed/service
# pattern set so it is not selectable, but leave the constant + engine intact.
CYCLE_PATTERNS = (CYCLE_PATTERN_ALL, CYCLE_PATTERN_OFFSET)

ANIMATION_OFF = "off"
ANIMATION_RAINBOW = "rainbow"
# "Animation" = decorative effects we render ourselves. Static Rainbow paints a
# frozen per-port rainbow; the Cycle entries animate. (KITT omitted for now.)
ANIMATION_LABELS = {
    ANIMATION_OFF: "Off",
    ANIMATION_RAINBOW: "Static Rainbow",
    CYCLE_PATTERN_ALL: "Cycle All",
    CYCLE_PATTERN_OFFSET: "Cycle Staggered",
}
ANIMATION_KEYS = tuple(ANIMATION_LABELS)
ANIMATION_KEY_BY_LABEL = {label: key for key, label in ANIMATION_LABELS.items()}

MODE_NETWORK = "network"
# Full low-level command map. Only the functional status modes are exposed in the
# UI (see MODE_LABELS); the reset/boot/locate entries stay here for completeness.
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

# "Mode" = built-in UniFi LED status indicators (driven by the firmware). These
# show real port state and are conceptually distinct from the Animation effects.
MODE_LABELS = {
    MODE_NETWORK: "Network",
    "speed": "Speed",
    "poe": "PoE",
    "device_type": "Device Type",
}

MODE_KEYS = tuple(MODE_LABELS)
MODE_KEY_BY_LABEL = {label: key for key, label in MODE_LABELS.items()}
