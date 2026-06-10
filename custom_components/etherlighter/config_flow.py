"""Config flow for Etherlighter."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .api import (
    AuthenticationFailed,
    CannotConnect,
    ConnectionResult,
    EtherlighterClient,
    EtherlighterError,
    HostKeyMismatch,
)
from .const import CONF_HOST_KEY_FINGERPRINT, DEFAULT_PORT, DOMAIN


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return config flow form schema."""

    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): cv.port,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


def _unique_id(result: ConnectionResult, host: str, port: int) -> str:
    """Return stable unique id for a device."""

    if result.info.mac:
        return result.info.mac.lower()
    return f"{host}:{port}"


def _title(result: ConnectionResult, host: str) -> str:
    """Return config entry title."""

    return result.info.hostname or result.info.model or host


async def _validate_input(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    expected_fingerprint: str | None = None,
) -> ConnectionResult:
    """Validate SSH details and return connection metadata."""

    api = EtherlighterClient(
        host=user_input[CONF_HOST],
        port=user_input[CONF_PORT],
        username=user_input[CONF_USERNAME],
        password=user_input[CONF_PASSWORD],
        expected_host_key_fingerprint=expected_fingerprint,
    )
    try:
        return await hass.async_add_executor_job(api.validate_connection)
    finally:
        await hass.async_add_executor_job(api.close)


class EtherlighterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an Etherlighter config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial setup step."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                result = await _validate_input(self.hass, user_input)
            except AuthenticationFailed:
                errors["base"] = "invalid_auth"
            except HostKeyMismatch:
                errors["base"] = "host_key_mismatch"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except EtherlighterError:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    _unique_id(result, user_input[CONF_HOST], user_input[CONF_PORT])
                )
                self._abort_if_unique_id_configured()
                data = dict(user_input)
                data[CONF_HOST_KEY_FINGERPRINT] = result.host_key_fingerprint
                return self.async_create_entry(
                    title=_title(result, user_input[CONF_HOST]),
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Allow users to update host or credentials."""

        entry = self._get_reconfigure_entry()
        defaults = {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_PORT: entry.data[CONF_PORT],
            CONF_USERNAME: entry.data[CONF_USERNAME],
        }
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                result = await _validate_input(self.hass, user_input)
            except AuthenticationFailed:
                errors["base"] = "invalid_auth"
            except HostKeyMismatch:
                errors["base"] = "host_key_mismatch"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except EtherlighterError:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    _unique_id(result, user_input[CONF_HOST], user_input[CONF_PORT])
                )
                self._abort_if_unique_id_mismatch()
                data = dict(user_input)
                data[CONF_HOST_KEY_FINGERPRINT] = result.host_key_fingerprint
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=data,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or defaults),
            errors=errors,
        )

    async def async_step_reauth(
        self, _entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle a request to refresh authentication or host-key trust."""

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm new SSH credentials and host-key trust."""

        entry = self._get_reauth_entry()
        defaults = {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_PORT: entry.data[CONF_PORT],
            CONF_USERNAME: entry.data[CONF_USERNAME],
        }
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                result = await _validate_input(self.hass, user_input)
            except AuthenticationFailed:
                errors["base"] = "invalid_auth"
            except HostKeyMismatch:
                errors["base"] = "host_key_mismatch"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except EtherlighterError:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    _unique_id(result, user_input[CONF_HOST], user_input[CONF_PORT])
                )
                self._abort_if_unique_id_mismatch()
                data = dict(user_input)
                data[CONF_HOST_KEY_FINGERPRINT] = result.host_key_fingerprint
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=data,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_schema(user_input or defaults),
            errors=errors,
        )
