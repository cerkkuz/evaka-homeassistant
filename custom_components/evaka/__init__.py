"""The Evaka Daycare Calendar integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import EvakaApi
from .const import CONF_MUNICIPALITY, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Evaka from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api = EvakaApi(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        municipality=entry.data[CONF_MUNICIPALITY],
    )

    # Attempt initial login
    if not await api.login():
        _LOGGER.error(
            "Failed to authenticate with Evaka. Please check your credentials."
        )
        # Still set up the integration - it will retry on data fetch
    else:
        _LOGGER.info("Successfully connected to Evaka")

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "municipality": entry.data[CONF_MUNICIPALITY],
    }

    # Register options flow handler
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        api: EvakaApi = data["api"]
        await api.close()

    return unload_ok
