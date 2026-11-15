"""Data update coordinator for the ICA shopping list."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IcaClient, IcaError, ShoppingList
from .api.exceptions import IcaAuthError, IcaGatewayBlockedError
from .const import CONF_LIST_ID, CONF_LIST_TITLE, DOMAIN, ISSUE_GATEWAY_BLOCKED

if TYPE_CHECKING:
    from . import IcaConfigEntry

_LOGGER = logging.getLogger(__name__)


class IcaDataUpdateCoordinator(DataUpdateCoordinator[ShoppingList]):
    """Polls a single ICA shopping list."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: IcaConfigEntry,
        client: IcaClient,
        list_id: str,
        interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="ICA shopping list",
            update_interval=timedelta(minutes=interval_minutes),
        )
        self._entry = config_entry
        self.client = client
        self.list_id = list_id

    async def _async_update_data(self) -> ShoppingList:
        try:
            data = await self.client.get_list(
                self.list_id, name=self._entry.data.get(CONF_LIST_TITLE)
            )
        except IcaGatewayBlockedError as err:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_GATEWAY_BLOCKED,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_GATEWAY_BLOCKED,
            )
            raise UpdateFailed(str(err)) from err
        except IcaAuthError as err:
            # Surfaces the HA reauth flow (spec: hard 401 -> reauth).
            raise ConfigEntryAuthFailed(str(err)) from err
        except IcaError as err:
            raise UpdateFailed(str(err)) from err
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_GATEWAY_BLOCKED)
        if data.id != self.list_id:
            self._migrate_list_id(data.id)
        return data

    def _migrate_list_id(self, new_id: str) -> None:
        """Store the list's current offlineId in place of a stale id.

        Entries configured against the retired web shopping-list API hold an
        id the mobile API may not know; `get_list` then finds the list by its
        server id or name instead. Persisting the offlineId it resolved means
        every later read and write addresses the list directly.
        """
        _LOGGER.info(
            "ICA shopping list id changed from %s to %s; updating the entry",
            self.list_id,
            new_id,
        )
        self.list_id = new_id
        entry = self._entry
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_LIST_ID: new_id}
        )
