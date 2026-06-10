"""Light platform for Etherlighter color control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EtherlighterDataUpdateCoordinator
from .entity import EtherlighterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Etherlighter light entities."""

    coordinator: EtherlighterDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EtherlighterLight(coordinator)])


class EtherlighterLight(EtherlighterEntity, LightEntity):
    """Static all-port RGB light control for one Etherlighting device."""

    _attr_color_mode = ColorMode.RGB
    _attr_icon = "mdi:led-strip-variant"
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(self, coordinator: EtherlighterDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "all_ports_light", "All Ports")

    @property
    def is_on(self) -> bool:
        """Return if the static color light is on."""

        return self.coordinator.light_is_on

    @property
    def brightness(self) -> int:
        """Return current brightness, 0..255."""

        return self.coordinator.current_brightness

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return current RGB color."""

        return self.coordinator.current_rgb_color

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set all ports to a static RGB color from the HA light UI."""

        raw_rgb_color = kwargs.get(ATTR_RGB_COLOR, self.coordinator.current_rgb_color)
        rgb_color = tuple(int(value) for value in raw_rgb_color)
        brightness = int(
            kwargs.get(ATTR_BRIGHTNESS, self.coordinator.current_brightness or 255)
        )
        await self.coordinator.async_set_static_color(rgb_color, brightness)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the static all-port color off."""

        await self.coordinator.async_set_static_color(
            self.coordinator.current_rgb_color,
            0,
        )
        self.async_write_ha_state()
