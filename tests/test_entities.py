"""Tests for Etherlighter Home Assistant entities."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import tempfile
from types import SimpleNamespace

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ColorMode
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity_platform import EntityPlatform

from custom_components.etherlighter.api import DeviceInfo
from custom_components.etherlighter.button import BUTTONS, BUTTON_NAMES, EtherlighterButton
from custom_components.etherlighter.const import (
    ANIMATION_LABELS,
    ANIMATION_RAINBOW,
    CYCLE_PATTERN_OFFSET,
    DOMAIN,
)
from custom_components.etherlighter.light import EtherlighterLight
from custom_components.etherlighter.number import (
    NUMBER_DESCRIPTIONS,
    NUMBER_NAMES,
    EtherlighterNumber,
)
from custom_components.etherlighter.select import (
    EtherlighterAnimationSelect,
    EtherlighterModeSelect,
)


class FakeCoordinator:
    """Coordinator stub for entity unit tests."""

    def __init__(self) -> None:
        self.entry = SimpleNamespace(
            unique_id="aa:bb:cc:dd:ee:ff",
            entry_id="entry-1",
            title="USWProMax16",
            data={"host": "192.0.2.10"},
        )
        self.data = DeviceInfo(
            hostname="USWProMax16",
            mac="aa:bb:cc:dd:ee:ff",
            model="USW-Pro-Max-16-PoE",
            version="1.0.0",
        )
        self.current_mode = None
        self.current_rgb_color = (255, 255, 255)
        self.current_brightness = 255
        self.light_is_on = False
        self.current_cycle_pattern = None
        self.transition_speed = 50
        self.animation_brightness = 100
        self.last_update_success = True
        self.static_color_calls: list[tuple[tuple[int, int, int], int]] = []
        self.started_animations: list[str] = []
        self.rainbow_calls = 0

    def async_add_listener(self, *args, **kwargs):
        """Register a coordinator listener."""

        return lambda: None

    async def async_set_static_color(
        self, rgb_color: tuple[int, int, int], brightness: int
    ) -> None:
        """Record static color updates."""

        self.current_rgb_color = rgb_color
        self.current_brightness = brightness
        self.light_is_on = brightness > 0
        self.static_color_calls.append((rgb_color, brightness))

    async def async_start_animation(self, pattern: str) -> None:
        """Record animation starts."""

        self.current_cycle_pattern = pattern
        self.started_animations.append(pattern)

    async def async_stop_cycle(self) -> None:
        """Record animation stop."""

        self.current_cycle_pattern = None

    async def async_set_transition_speed(self, speed: int) -> None:
        """Record transition speed updates."""

        self.transition_speed = speed

    async def async_set_animation_brightness(self, brightness: int) -> None:
        """Record animation brightness updates."""

        self.animation_brightness = brightness

    async def async_set_static_rainbow(self) -> None:
        """Record static rainbow paints."""

        self.rainbow_calls += 1
        self.current_mode = None
        self.current_cycle_pattern = ANIMATION_RAINBOW
        self.light_is_on = True


def test_select_entity_has_name_unique_id_and_device_info() -> None:
    entity = EtherlighterModeSelect(FakeCoordinator())

    assert entity.name == "Mode"
    assert entity.unique_id == "aa:bb:cc:dd:ee:ff_mode"
    assert entity.device_info["name"] == "USWProMax16"
    assert entity.device_info["model"] == "USW-Pro-Max-16-PoE"
    assert entity.device_info["connections"] == {
        (CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")
    }


def test_animation_select_static_rainbow_and_cycle() -> None:
    coordinator = FakeCoordinator()
    entity = EtherlighterAnimationSelect(coordinator)
    entity.async_write_ha_state = lambda: None

    assert entity.name == "Animation"
    assert entity.unique_id == "aa:bb:cc:dd:ee:ff_animation"
    assert entity.current_option == ANIMATION_LABELS["off"]

    asyncio.run(entity.async_select_option(ANIMATION_LABELS[ANIMATION_RAINBOW]))
    assert coordinator.rainbow_calls == 1
    assert entity.current_option == ANIMATION_LABELS[ANIMATION_RAINBOW]

    asyncio.run(entity.async_select_option(ANIMATION_LABELS[CYCLE_PATTERN_OFFSET]))
    assert coordinator.started_animations == [CYCLE_PATTERN_OFFSET]
    assert entity.current_option == ANIMATION_LABELS[CYCLE_PATTERN_OFFSET]


def test_stop_cycle_button_stops_animation() -> None:
    coordinator = FakeCoordinator()
    coordinator.current_cycle_pattern = "all"
    [button] = [EtherlighterButton(coordinator, item) for item in BUTTONS]
    button.async_write_ha_state = lambda: None

    assert button.name == BUTTON_NAMES["stop_cycle"]
    assert button.unique_id == "aa:bb:cc:dd:ee:ff_stop_cycle"

    asyncio.run(button.async_press())

    assert coordinator.current_cycle_pattern is None


def test_number_entities_update_animation_controls() -> None:
    coordinator = FakeCoordinator()
    entities = {
        description.key: EtherlighterNumber(coordinator, description)
        for description in NUMBER_DESCRIPTIONS
    }
    for entity in entities.values():
        entity.async_write_ha_state = lambda: None

    assert entities["transition_speed"].name == NUMBER_NAMES["transition_speed"]
    assert entities["transition_speed"].native_value == 50
    asyncio.run(entities["transition_speed"].async_set_native_value(75))
    asyncio.run(entities["animation_brightness"].async_set_native_value(60))

    assert coordinator.transition_speed == 75
    assert coordinator.animation_brightness == 60


def test_light_entity_exposes_rgb_color_control() -> None:
    coordinator = FakeCoordinator()
    entity = EtherlighterLight(coordinator)
    entity.async_write_ha_state = lambda: None

    assert entity.name == "All Ports"
    assert entity.unique_id == "aa:bb:cc:dd:ee:ff_all_ports_light"
    assert entity.supported_color_modes == {ColorMode.RGB}
    assert entity.rgb_color == (255, 255, 255)
    assert entity.brightness == 255
    assert entity.is_on is False

    asyncio.run(
        entity.async_turn_on(
            **{
                ATTR_RGB_COLOR: (10, 20, 30),
                ATTR_BRIGHTNESS: 128,
            }
        )
    )

    assert coordinator.static_color_calls == [((10, 20, 30), 128)]
    assert entity.rgb_color == (10, 20, 30)
    assert entity.brightness == 128
    assert entity.is_on is True


def test_entities_register_with_home_assistant_device_registry() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hass = HomeAssistant(tmp)
            dr.async_setup(hass)
            await ar.async_load(hass, load_empty=True)
            await dr.async_load(hass, load_empty=True)
            await er.async_load(hass, load_empty=True)

            entry = ConfigEntry(
                version=1,
                minor_version=1,
                domain=DOMAIN,
                title="USWProMax16",
                data={CONF_HOST: "192.0.2.10"},
                options={},
                source=SOURCE_USER,
                unique_id="aa:bb:cc:dd:ee:ff",
                discovery_keys={},
                subentries_data=[],
                state=ConfigEntryState.LOADED,
            )
            hass.config_entries = SimpleNamespace(
                async_get_entry=lambda entry_id: entry
            )
            coordinator = FakeCoordinator()
            coordinator.entry = entry

            created: dict[str, list[str]] = {}
            for domain, entities in [
                (
                    "select",
                    [
                        EtherlighterModeSelect(coordinator),
                        EtherlighterAnimationSelect(coordinator),
                    ],
                ),
                ("button", [EtherlighterButton(coordinator, item) for item in BUTTONS]),
                ("light", [EtherlighterLight(coordinator)]),
                (
                    "number",
                    [
                        EtherlighterNumber(coordinator, item)
                        for item in NUMBER_DESCRIPTIONS
                    ],
                ),
            ]:
                platform = EntityPlatform(
                    hass=hass,
                    logger=logging.getLogger(domain),
                    domain=domain,
                    platform_name=DOMAIN,
                    platform=None,
                    scan_interval=timedelta(seconds=30),
                    entity_namespace=None,
                )
                platform.config_entry = entry
                await platform.async_add_entities(entities)
                created[domain] = sorted(platform.entities)

            assert created["select"] == [
                "select.uswpromax16_animation",
                "select.uswpromax16_mode",
            ]
            assert created["button"] == ["button.uswpromax16_stop_cycle"]
            assert created["light"] == ["light.uswpromax16_all_ports"]
            assert created["number"] == [
                "number.uswpromax16_animation_brightness",
                "number.uswpromax16_transition_speed",
            ]
            assert len(dr.async_get(hass).devices) == 1
            await hass.async_stop()

    asyncio.run(run())
