"""Data coordinator for the Etherlighter integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AuthenticationFailed,
    CannotConnect,
    DeviceInfo,
    EtherlighterClient,
    EtherlighterError,
    HostKeyMismatch,
)
from .const import DOMAIN, MODE_COMMANDS

_LOGGER = logging.getLogger(__name__)


class EtherlighterDataUpdateCoordinator(DataUpdateCoordinator[DeviceInfo]):
    """Coordinate device metadata and command execution."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: EtherlighterClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
        )
        self.entry = entry
        self.api = api
        self.current_mode: str | None = None
        self.current_cycle_pattern: str | None = None

    async def _async_update_data(self) -> DeviceInfo:
        try:
            return await self.hass.async_add_executor_job(self.api.info)
        except (AuthenticationFailed, HostKeyMismatch) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (CannotConnect, EtherlighterError) as err:
            raise UpdateFailed(str(err)) from err

    async def async_set_mode(self, mode: str) -> None:
        """Set device mode."""

        if mode not in MODE_COMMANDS:
            raise HomeAssistantError(f"Unsupported Etherlighter mode: {mode}")
        await self.hass.async_add_executor_job(self.api.set_mode, mode)
        self.current_mode = mode
        self.current_cycle_pattern = None
        self.async_set_updated_data(self.data)

    async def async_start_cycle(
        self, pattern: str, interval: float, brightness: int
    ) -> None:
        """Start an Etherlighter color cycle."""

        await self.hass.async_add_executor_job(
            self.api.start_color_cycle,
            pattern,
            interval,
            brightness,
        )
        self.current_mode = None
        self.current_cycle_pattern = pattern
        self.async_set_updated_data(self.data)

    async def async_stop_cycle(self) -> None:
        """Stop an Etherlighter color cycle."""

        await self.hass.async_add_executor_job(self.api.stop_color_cycle)
        self.current_cycle_pattern = None
        self.async_set_updated_data(self.data)
