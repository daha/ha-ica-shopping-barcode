"""Tests for config-entry setup/unload and coordinator dedupe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.exceptions import IcaAuthError, IcaGatewayBlockedError
from custom_components.ica.api.models import ShoppingList, ShoppingListItem
from custom_components.ica.const import (
    CONF_LIST_ID,
    CONF_TOKEN,
    DOMAIN,
    ISSUE_GATEWAY_BLOCKED,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _entry() -> MockConfigEntry:
    token = IcaToken("a", "r", datetime.now(UTC) + timedelta(hours=1), "c", "s", "sc")
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TOKEN: token.to_dict(),
            CONF_LIST_ID: "G1",
            "list_title": "Inköpslista",
        },
        entry_id="entry1",
    )


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    lst = ShoppingList(
        id="G1",
        name="Inköpslista",
        items=[ShoppingListItem("R1", "Mjölk", False)],
    )
    with patch("custom_components.ica.IcaClient.get_list", AsyncMock(return_value=lst)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data.coordinator
    assert coordinator.data is not None
    assert coordinator.data.has_active_item("mjölk") is True
    assert coordinator.data.has_active_item("saknas") is False

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_error_triggers_reauth(hass: HomeAssistant) -> None:
    # A4: a hard 401 during the coordinator's first refresh must fail setup
    # and start the HA reauth flow (ConfigEntryAuthFailed path).
    entry = _entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.ica.IcaClient.get_list",
        AsyncMock(side_effect=IcaAuthError("401")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.async_get_active_flows(hass, {"reauth"})


async def test_coordinator_gateway_blocked_and_recovery(hass: HomeAssistant) -> None:
    # A4: the coordinator's own gateway-blocked branch must create the
    # `gateway_blocked` repair issue, and a subsequent successful refresh
    # must delete it again.
    entry = _entry()
    entry.add_to_hass(hass)

    lst = ShoppingList(
        id="G1",
        name="Inköpslista",
        items=[ShoppingListItem("R1", "Mjölk", False)],
    )
    with patch("custom_components.ica.IcaClient.get_list", AsyncMock(return_value=lst)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator

    with patch(
        "custom_components.ica.IcaClient.get_list",
        AsyncMock(side_effect=IcaGatewayBlockedError("403")),
    ):
        await coordinator.async_refresh()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_GATEWAY_BLOCKED)
    assert issue is not None

    with patch("custom_components.ica.IcaClient.get_list", AsyncMock(return_value=lst)):
        await coordinator.async_refresh()

    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_GATEWAY_BLOCKED) is None
