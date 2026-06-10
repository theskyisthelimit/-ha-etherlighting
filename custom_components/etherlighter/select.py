"""Select platform for Etherlighter modes."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_KEY_BY_LABEL, MODE_LABELS
from .coordinator import EtherlighterDataUpdateCoordinator
from .entity import EtherlighterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Etherlighter select entities."""

    coordinator: EtherlighterDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EtherlighterModeSelect(coordinator)])


class EtherlighterModeSelect(EtherlighterEntity, SelectEntity):
    """Mode selector for one Etherlighting device."""

    _attr_translation_key = "mode"
    _attr_icon = "mdi:led-strip-variant"

    def __init__(self, coordinator: EtherlighterDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "mode", "Mode")
        self._attr_options = list(MODE_LABELS.values())

    @property
    def current_option(self) -> str | None:
        """Return the currently selected mode."""

        mode = self.coordinator.current_mode
        if mode is None:
            return None
        return MODE_LABELS.get(mode)

    async def async_select_option(self, option: str) -> None:
        """Change the selected mode from the UI."""

        mode = MODE_KEY_BY_LABEL.get(option)
        if mode is None:
            raise HomeAssistantError(f"Unsupported Etherlighter option: {option}")
        await self._async_set_mode(mode)

    async def async_service_set_mode(self, mode: str) -> None:
        """Handle etherlighter.set_mode service action."""

        await self._async_set_mode(mode)

    async def async_service_start_cycle(
        self, pattern: str, interval: float, brightness: int
    ) -> None:
        """Handle etherlighter.start_cycle service action."""

        await self.coordinator.async_start_cycle(pattern, interval, brightness)
        self.async_write_ha_state()

    async def async_service_stop_cycle(self) -> None:
        """Handle etherlighter.stop_cycle service action."""

        await self.coordinator.async_stop_cycle()
        self.async_write_ha_state()

    async def _async_set_mode(self, mode: str) -> None:
        """Set the mode and update state."""

        await self.coordinator.async_set_mode(mode)
        self.async_write_ha_state()
