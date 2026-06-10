"""Home Assistant integration for UniFi Etherlighting devices."""

from __future__ import annotations

from .const import DOMAIN


async def async_setup(hass, config) -> bool:
    """Set up Etherlighter services."""

    import voluptuous as vol

    from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
    from homeassistant.helpers import service

    from .const import (
        ATTR_BRIGHTNESS,
        ATTR_INTERVAL,
        ATTR_MODE,
        ATTR_PATTERN,
        CYCLE_PATTERNS,
        DEFAULT_CYCLE_BRIGHTNESS,
        DEFAULT_CYCLE_INTERVAL,
        MODE_KEYS,
        SERVICE_SET_MODE,
        SERVICE_START_CYCLE,
        SERVICE_STOP_CYCLE,
    )

    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_MODE,
        entity_domain=SELECT_DOMAIN,
        schema={vol.Required(ATTR_MODE): vol.In(MODE_KEYS)},
        func="async_service_set_mode",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_START_CYCLE,
        entity_domain=SELECT_DOMAIN,
        schema={
            vol.Required(ATTR_PATTERN): vol.In(CYCLE_PATTERNS),
            vol.Optional(ATTR_INTERVAL, default=DEFAULT_CYCLE_INTERVAL): vol.All(
                vol.Coerce(float), vol.Range(min=0.05, max=5)
            ),
            vol.Optional(
                ATTR_BRIGHTNESS, default=DEFAULT_CYCLE_BRIGHTNESS
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        },
        func="async_service_start_cycle",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_STOP_CYCLE,
        entity_domain=SELECT_DOMAIN,
        schema={},
        func="async_service_stop_cycle",
    )
    return True


async def async_setup_entry(hass, entry) -> bool:
    """Set up Etherlighter from a config entry."""

    from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
    from homeassistant.const import Platform

    from .api import EtherlighterClient
    from .const import CONF_HOST_KEY_FINGERPRINT
    from .coordinator import EtherlighterDataUpdateCoordinator

    api = EtherlighterClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        expected_host_key_fingerprint=entry.data.get(CONF_HOST_KEY_FINGERPRINT),
    )
    coordinator = EtherlighterDataUpdateCoordinator(hass, entry, api)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await hass.async_add_executor_job(api.close)
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.SELECT, Platform.LIGHT, Platform.NUMBER]
    )
    return True


async def async_unload_entry(hass, entry) -> bool:
    """Unload an Etherlighter config entry."""

    from homeassistant.const import Platform

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform.SELECT, Platform.LIGHT, Platform.NUMBER]
    )
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(coordinator.api.close)
    return unload_ok
