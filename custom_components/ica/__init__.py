"""ICA Shopping List integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import IcaClient
from .api.auth import IcaAuth, IcaToken
from .const import (
    CONF_LIST_ID,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import IcaDataUpdateCoordinator
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class IcaRuntimeData:
    """Runtime objects stored on the config entry."""

    client: IcaClient
    coordinator: IcaDataUpdateCoordinator


type IcaConfigEntry = ConfigEntry[IcaRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ICA integration (register services once, for its lifetime)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IcaConfigEntry) -> bool:
    """Set up ICA from a config entry."""
    session = async_get_clientsession(hass)
    token = IcaToken.from_dict(entry.data[CONF_TOKEN])

    async def _save_token(new_token: IcaToken) -> None:
        # Persist refreshed tokens back to the config entry (single source of
        # truth). The update listener below only re-applies the poll interval,
        # so this does NOT trigger a reload loop.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: new_token.to_dict()}
        )

    auth = IcaAuth(session, token=token, token_updated=_save_token)
    client = IcaClient(session, auth)

    interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = IcaDataUpdateCoordinator(
        hass, entry, client, entry.data[CONF_LIST_ID], interval
    )
    # first_refresh raises ConfigEntryNotReady / ConfigEntryAuthFailed itself
    # based on what the coordinator raised (UpdateFailed / ConfigEntryAuthFailed).
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = IcaRuntimeData(client=client, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IcaConfigEntry) -> bool:
    """Unload a config entry.

    Services are registered once in `async_setup` and live for the
    integration's lifetime — they are intentionally NOT unregistered here.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: IcaConfigEntry) -> None:
    """Apply changed options (poll interval) live, without a full reload.

    This runs on every entry update, including token refreshes — it must stay
    idempotent and side-effect-free beyond re-setting the interval.
    """
    entry.runtime_data.coordinator.update_interval = timedelta(
        minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
