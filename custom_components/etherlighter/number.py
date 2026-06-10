"""Number platform for Etherlighter animation controls."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EtherlighterDataUpdateCoordinator
from .entity import EtherlighterEntity


NUMBER_DESCRIPTIONS = (
    NumberEntityDescription(
        key="transition_speed",
        translation_key="transition_speed",
        icon="mdi:speedometer",
        native_min_value=1,
        native_max_value=100,
        native_step=1,
    ),
    NumberEntityDescription(
        key="animation_brightness",
        translation_key="animation_brightness",
        icon="mdi:brightness-6",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
    ),
    NumberEntityDescription(
        key="scanner_tail",
        translation_key="scanner_tail",
        icon="mdi:tailwind",
        native_min_value=1,
        native_max_value=8,
        native_step=1,
    ),
)

NUMBER_NAMES = {
    "transition_speed": "Transition Speed",
    "animation_brightness": "Animation Brightness",
    "scanner_tail": "Scanner Tail",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Etherlighter number entities."""

    coordinator: EtherlighterDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [EtherlighterNumber(coordinator, description) for description in NUMBER_DESCRIPTIONS]
    )


class EtherlighterNumber(EtherlighterEntity, NumberEntity):
    """Number entity for one animation control."""

    def __init__(
        self,
        coordinator: EtherlighterDataUpdateCoordinator,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, NUMBER_NAMES[description.key])
        self.entity_description = description

    @property
    def native_value(self) -> float:
        """Return current control value."""

        key = self.entity_description.key
        if key == "transition_speed":
            return self.coordinator.transition_speed
        if key == "animation_brightness":
            return self.coordinator.animation_brightness
        return self.coordinator.scanner_tail

    async def async_set_native_value(self, value: float) -> None:
        """Set a control value."""

        key = self.entity_description.key
        if key == "transition_speed":
            await self.coordinator.async_set_transition_speed(round(value))
        elif key == "animation_brightness":
            await self.coordinator.async_set_animation_brightness(round(value))
        elif key == "scanner_tail":
            await self.coordinator.async_set_scanner_tail(round(value))
        self.async_write_ha_state()
