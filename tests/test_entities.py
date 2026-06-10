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
from custom_components.etherlighter.const import DOMAIN
from custom_components.etherlighter.light import EtherlighterLight
from custom_components.etherlighter.select import EtherlighterModeSelect


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
        self.last_update_success = True
        self.static_color_calls: list[tuple[tuple[int, int, int], int]] = []

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


def test_select_entity_has_name_unique_id_and_device_info() -> None:
    entity = EtherlighterModeSelect(FakeCoordinator())

    assert entity.name == "Mode"
    assert entity.unique_id == "aa:bb:cc:dd:ee:ff_mode"
    assert entity.device_info["name"] == "USWProMax16"
    assert entity.device_info["model"] == "USW-Pro-Max-16-PoE"
    assert entity.device_info["connections"] == {
        (CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")
    }


def test_button_entities_have_names_and_unique_ids() -> None:
    coordinator = FakeCoordinator()

    for description in BUTTONS:
        entity = EtherlighterButton(coordinator, description)
        assert entity.name == BUTTON_NAMES[description.key]
        assert entity.unique_id == f"aa:bb:cc:dd:ee:ff_{description.key}"


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
                ("select", [EtherlighterModeSelect(coordinator)]),
                ("button", [EtherlighterButton(coordinator, item) for item in BUTTONS]),
                ("light", [EtherlighterLight(coordinator)]),
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

            assert created["select"] == ["select.uswpromax16_mode"]
            assert created["button"] == [
                "button.uswpromax16_cycle_all",
                "button.uswpromax16_cycle_staggered",
                "button.uswpromax16_network_standard",
                "button.uswpromax16_stop_cycle",
            ]
            assert created["light"] == ["light.uswpromax16_all_ports"]
            assert len(dr.async_get(hass).devices) == 1
            await hass.async_stop()

    asyncio.run(run())
