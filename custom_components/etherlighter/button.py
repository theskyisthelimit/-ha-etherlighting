"""Button platform for Etherlighter actions."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EtherlighterDataUpdateCoordinator
from .entity import EtherlighterEntity


BUTTONS = (
    ButtonEntityDescription(
        key="stop_cycle",
        translation_key="stop_cycle",
        icon="mdi:stop-circle-outline",
    ),
)

BUTTON_NAMES = {
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

        if self.entity_description.key == "stop_cycle":
            await self.coordinator.async_stop_cycle()
