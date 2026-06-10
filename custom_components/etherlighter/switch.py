"""Switch platform for Etherlighter effect toggles."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_NETWORK, MODE_WARM_RESET
from .coordinator import EtherlighterDataUpdateCoordinator
from .entity import EtherlighterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Etherlighter switch entities."""

    coordinator: EtherlighterDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EtherlighterBreathingSwitch(coordinator)])


class EtherlighterBreathingSwitch(EtherlighterEntity, SwitchEntity):
    """Toggle the built-in white breathing effect (UniFi warm reset)."""

    _attr_translation_key = "breathing"
    _attr_icon = "mdi:lungs"

    def __init__(self, coordinator: EtherlighterDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "breathing", "Breathing Effect")

    @property
    def is_on(self) -> bool:
        """Return whether the breathing effect is currently active."""

        return self.coordinator.current_mode == MODE_WARM_RESET

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the built-in white breathing effect."""

        await self.coordinator.async_set_mode(MODE_WARM_RESET)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop breathing and restore the standard network mode."""

        await self.coordinator.async_set_mode(MODE_NETWORK)
        self.async_write_ha_state()
