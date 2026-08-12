"""Tests for config-entry setup/unload and coordinator dedupe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.models import ShoppingList, ShoppingListItem
from custom_components.ica.const import CONF_LIST_ID, CONF_TOKEN, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
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
    assert coordinator.has_item("mjölk") is True
    assert coordinator.has_item("saknas") is False

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
