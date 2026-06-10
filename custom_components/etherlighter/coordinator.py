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
from .const import (
    ANIMATION_RAINBOW,
    DEFAULT_CYCLE_STEPS,
    DEFAULT_CYCLE_BRIGHTNESS,
    DEFAULT_SCANNER_TAIL,
    DEFAULT_TRANSITION_SPEED,
    DOMAIN,
    MODE_COMMANDS,
)

_LOGGER = logging.getLogger(__name__)


def transition_speed_to_interval(speed: int) -> float:
    """Map user-facing speed 1..100 to frame interval seconds."""

    speed = max(1, min(100, round(speed)))
    if speed <= 50:
        return round(1.0 - ((speed - 1) / 49) * 0.8, 3)
    return round(0.2 - ((speed - 50) / 50) * 0.15, 3)


def interval_to_transition_speed(interval: float) -> int:
    """Map frame interval seconds back to user-facing speed 1..100."""

    interval = max(0.05, min(1.0, interval))
    if interval >= 0.2:
        return round(1 + ((1.0 - interval) / 0.8) * 49)
    return round(50 + ((0.2 - interval) / 0.15) * 50)


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
        self.current_rgb_color: tuple[int, int, int] = (255, 255, 255)
        self.current_brightness: int = 255
        self.light_is_on = False
        self.transition_speed = DEFAULT_TRANSITION_SPEED
        self.animation_brightness = DEFAULT_CYCLE_BRIGHTNESS
        self.scanner_tail = DEFAULT_SCANNER_TAIL

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
        self.light_is_on = False
        self.async_set_updated_data(self.data)

    async def async_start_cycle(
        self, pattern: str, interval: float, brightness: int
    ) -> None:
        """Start an Etherlighter color cycle."""

        self.transition_speed = interval_to_transition_speed(interval)
        self.animation_brightness = brightness
        await self.hass.async_add_executor_job(
            self.api.start_color_cycle,
            pattern,
            interval,
            brightness,
            DEFAULT_CYCLE_STEPS,
            self.scanner_tail,
        )
        self.current_mode = None
        self.current_cycle_pattern = pattern
        self.light_is_on = True
        self.async_set_updated_data(self.data)

    async def async_start_animation(self, pattern: str) -> None:
        """Start an animation with current UI control values."""

        await self.hass.async_add_executor_job(
            self.api.start_color_cycle,
            pattern,
            transition_speed_to_interval(self.transition_speed),
            self.animation_brightness,
            DEFAULT_CYCLE_STEPS,
            self.scanner_tail,
        )
        self.current_mode = None
        self.current_cycle_pattern = pattern
        self.light_is_on = True
        self.async_set_updated_data(self.data)

    async def async_set_static_rainbow(self) -> None:
        """Paint a frozen per-port rainbow at the current animation brightness."""

        await self.hass.async_add_executor_job(
            self.api.set_static_rainbow, self.animation_brightness
        )
        self.current_mode = None
        self.current_cycle_pattern = ANIMATION_RAINBOW
        self.light_is_on = True
        self.async_set_updated_data(self.data)

    async def async_stop_cycle(self) -> None:
        """Stop an Etherlighter color cycle."""

        await self.hass.async_add_executor_job(self.api.stop_color_cycle)
        self.current_cycle_pattern = None
        self.async_set_updated_data(self.data)

    async def async_set_transition_speed(self, speed: int) -> None:
        """Set animation speed and update any running animation."""

        self.transition_speed = max(1, min(100, round(speed)))
        if self.current_cycle_pattern is not None:
            await self.hass.async_add_executor_job(
                self.api.update_color_cycle_settings,
                transition_speed_to_interval(self.transition_speed),
                None,
                None,
            )
        self.async_set_updated_data(self.data)

    async def async_set_animation_brightness(self, brightness: int) -> None:
        """Set animation brightness and update any running animation."""

        self.animation_brightness = max(0, min(100, round(brightness)))
        if self.current_cycle_pattern == ANIMATION_RAINBOW:
            await self.hass.async_add_executor_job(
                self.api.set_static_rainbow, self.animation_brightness
            )
        elif self.current_cycle_pattern is not None:
            await self.hass.async_add_executor_job(
                self.api.update_color_cycle_settings,
                None,
                self.animation_brightness,
                None,
            )
        self.async_set_updated_data(self.data)

    async def async_set_scanner_tail(self, scanner_tail: int) -> None:
        """Set KITT scanner tail length and update any running animation."""

        self.scanner_tail = max(1, min(8, round(scanner_tail)))
        if self.current_cycle_pattern is not None:
            await self.hass.async_add_executor_job(
                self.api.update_color_cycle_settings,
                None,
                None,
                self.scanner_tail,
            )
        self.async_set_updated_data(self.data)

    async def async_set_static_color(
        self, rgb_color: tuple[int, int, int], brightness: int
    ) -> None:
        """Set all device ports to one static color."""

        from .api import Color

        percent_brightness = round(brightness * 100 / 255)
        await self.hass.async_add_executor_job(
            self.api.set_static_color,
            Color(*rgb_color),
            percent_brightness,
        )
        self.current_mode = None
        self.current_cycle_pattern = None
        self.current_rgb_color = rgb_color
        self.current_brightness = brightness
        self.light_is_on = brightness > 0
        self.async_set_updated_data(self.data)
