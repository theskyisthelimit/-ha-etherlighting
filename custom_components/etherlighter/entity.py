"""Base entities for Etherlighter."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EtherlighterDataUpdateCoordinator


class EtherlighterEntity(CoordinatorEntity[EtherlighterDataUpdateCoordinator]):
    """Base Etherlighter entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EtherlighterDataUpdateCoordinator,
        suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        unique_base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique_base}_{suffix}"
        self._attr_name = name

    @property
    def device_info(self):
        """Return device registry information."""

        entry = self.coordinator.entry
        info = self.coordinator.data
        identifiers = {(DOMAIN, entry.unique_id or entry.entry_id)}
        device_info = {
            "identifiers": identifiers,
            "manufacturer": "Ubiquiti",
            "name": info.hostname or entry.title,
            "model": info.model or None,
            "sw_version": info.version or None,
        }
        if info.mac:
            device_info["connections"] = {
                (CONNECTION_NETWORK_MAC, info.mac.lower())
            }
        return device_info
