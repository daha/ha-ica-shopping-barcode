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
from .const import DOMAIN, ISSUE_GATEWAY_BLOCKED

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
        self.client = client
        self.list_id = list_id

    async def _async_update_data(self) -> ShoppingList:
        try:
            data = await self.client.get_list(self.list_id)
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
        return data
