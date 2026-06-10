"""Button platform for Etherlighter actions."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CYCLE_PATTERN_ALL,
    CYCLE_PATTERN_OFFSET,
    DEFAULT_CYCLE_BRIGHTNESS,
    DEFAULT_CYCLE_INTERVAL,
    DOMAIN,
    MODE_NETWORK,
)
from .coordinator import EtherlighterDataUpdateCoordinator
from .entity import EtherlighterEntity


BUTTONS = (
    ButtonEntityDescription(
        key="network",
        translation_key="network_standard",
        icon="mdi:lan",
    ),
    ButtonEntityDescription(
        key="cycle_all",
        translation_key="cycle_all",
        icon="mdi:palette",
    ),
    ButtonEntityDescription(
        key="cycle_offset",
        translation_key="cycle_staggered",
        icon="mdi:gradient-horizontal",
    ),
    ButtonEntityDescription(
        key="stop_cycle",
        translation_key="stop_cycle",
        icon="mdi:stop-circle-outline",
    ),
)

BUTTON_NAMES = {
    "network": "Network Standard",
    "cycle_all": "Cycle All",
    "cycle_offset": "Cycle Staggered",
    "stop_cycle": "Stop Cycle",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Etherlighter button entities."""

    coordinator: EtherlighterDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [EtherlighterButton(coordinator, description) for description in BUTTONS]
    )


class EtherlighterButton(EtherlighterEntity, ButtonEntity):
    """Button entity for one Etherlighter action."""

    def __init__(
        self,
        coordinator: EtherlighterDataUpdateCoordinator,
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, BUTTON_NAMES[description.key])
        self.entity_description = description

    async def async_press(self) -> None:
        """Run the button action."""

        key = self.entity_description.key
        if key == "network":
            await self.coordinator.async_set_mode(MODE_NETWORK)
        elif key == "cycle_all":
            await self.coordinator.async_start_cycle(
                CYCLE_PATTERN_ALL,
                DEFAULT_CYCLE_INTERVAL,
                DEFAULT_CYCLE_BRIGHTNESS,
            )
        elif key == "cycle_offset":
            await self.coordinator.async_start_cycle(
                CYCLE_PATTERN_OFFSET,
                DEFAULT_CYCLE_INTERVAL,
                DEFAULT_CYCLE_BRIGHTNESS,
            )
        elif key == "stop_cycle":
            await self.coordinator.async_stop_cycle()
