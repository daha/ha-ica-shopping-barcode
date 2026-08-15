"""Tests for the ICA to-do list entity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.exceptions import IcaAuthError, IcaError
from custom_components.ica.api.models import ShoppingList, ShoppingListItem
from custom_components.ica.const import (
    CONF_LIST_ID,
    CONF_LIST_TITLE,
    CONF_TOKEN,
    DOMAIN,
)
from homeassistant.components.todo.const import DATA_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

REFRESH = (
    "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh"
)


def _token_dict() -> dict[str, str]:
    return IcaToken(
        "a", "r", datetime.now(UTC) + timedelta(hours=1), "c", "s", "sc"
    ).to_dict()


async def _setup(hass: HomeAssistant, items: list[ShoppingListItem]) -> str:
    """Set the integration up and return the to-do entity id."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TOKEN: _token_dict(),
            CONF_LIST_ID: "G1",
            CONF_LIST_TITLE: "Inköpslista",
        },
        entry_id="e1",
    )
    entry.add_to_hass(hass)
    lst = ShoppingList(id="G1", name="Inköpslista", items=items)
    with patch("custom_components.ica.IcaClient.get_list", AsyncMock(return_value=lst)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entity_ids = hass.states.async_entity_ids("todo")
    assert entity_ids, "no todo entity was created"
    return entity_ids[0]


async def test_entity_exposes_rows_as_items(hass: HomeAssistant) -> None:
    entity_id = await _setup(
        hass,
        [
            ShoppingListItem("R1", "Mjölk", False),
            ShoppingListItem("R2", "Bröd", True),
        ],
    )
    state = hass.states.get(entity_id)
    assert state is not None
    # A to-do entity's state is its count of not-yet-done items.
    assert state.state == "1"

    result = await hass.services.async_call(
        "todo",
        "get_items",
        {},
        target={"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    items = result[entity_id]["items"]
    by_summary = {i["summary"]: i for i in items}
    assert by_summary["Mjölk"]["status"] == "needs_action"
    assert by_summary["Bröd"]["status"] == "completed"
    assert by_summary["Mjölk"]["uid"] == "R1"


async def test_create_item_does_not_dedupe(hass: HomeAssistant) -> None:
    # UI/voice adds always add, unlike the scanner services (spec §6).
    entity_id = await _setup(hass, [ShoppingListItem("R1", "Mjölk", False)])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.add_item", AsyncMock()
        ) as add,
        patch(REFRESH, AsyncMock()) as refresh,
    ):
        await hass.services.async_call(
            "todo",
            "add_item",
            {"item": "Mjölk"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    add.assert_awaited_once_with("G1", "Mjölk")
    refresh.assert_awaited_once()


async def test_check_off_item_preserves_the_rest_of_the_row(
    hass: HomeAssistant,
) -> None:
    row = ShoppingListItem.from_api(
        {
            "id": "R1",
            "text": "Mjölk",
            "isStriked": False,
            "article": {"id": 11103, "group": {"id": 10}},
        }
    )
    entity_id = await _setup(hass, [row])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.update_item", AsyncMock()
        ) as update,
        patch(REFRESH, AsyncMock()) as refresh,
    ):
        await hass.services.async_call(
            "todo",
            "update_item",
            {"item": "Mjölk", "status": "completed"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    args, kwargs = update.await_args
    assert args[0].id == "R1"
    # The client is handed the ROW, so the untouched fields ride along.
    assert args[0].raw["article"] == {"id": 11103, "group": {"id": 10}}
    assert kwargs["is_checked"] is True
    refresh.assert_awaited_once()


async def test_rename_item(hass: HomeAssistant) -> None:
    # Checked row: a plain rename must not silently uncheck it.
    entity_id = await _setup(hass, [ShoppingListItem("R1", "mjolk", True)])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.update_item", AsyncMock()
        ) as update,
        patch(REFRESH, AsyncMock()),
    ):
        await hass.services.async_call(
            "todo",
            "update_item",
            {"item": "mjolk", "rename": "Mjölk"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    _, kwargs = update.await_args
    assert kwargs["text"] == "Mjölk"
    assert kwargs["is_checked"] is True  # a rename must not uncheck the row


async def test_add_item_auth_error_starts_reauth(hass: HomeAssistant) -> None:
    # This is the whole justification for extracting errors.py: any ICA
    # write that hits a 401 must kick off HA's reauth flow.
    entity_id = await _setup(hass, [ShoppingListItem("R1", "Mjölk", False)])
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.add_item",
            AsyncMock(side_effect=IcaAuthError("401")),
        ),
        patch.object(entry, "async_start_reauth", MagicMock()) as start_reauth,
        patch(REFRESH, AsyncMock()),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "todo",
            "add_item",
            {"item": "Ost"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    start_reauth.assert_called_once()


async def test_remove_item(hass: HomeAssistant) -> None:
    entity_id = await _setup(hass, [ShoppingListItem("R1", "Mjölk", False)])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.remove_item", AsyncMock()
        ) as remove,
        patch(REFRESH, AsyncMock()) as refresh,
    ):
        await hass.services.async_call(
            "todo",
            "remove_item",
            {"item": "Mjölk"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    remove.assert_awaited_once_with("R1")
    refresh.assert_awaited_once()


async def test_delete_multiple_items(hass: HomeAssistant) -> None:
    # The "remove completed items" card action sends several uids at once —
    # i.e. CHECKED rows, so that's what this test represents.
    entity_id = await _setup(
        hass,
        [
            ShoppingListItem("R1", "Mjölk", True),
            ShoppingListItem("R2", "Bröd", True),
        ],
    )
    entity = hass.data[DATA_COMPONENT].get_entity(entity_id)
    assert entity is not None
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.remove_item", AsyncMock()
        ) as remove,
        patch(REFRESH, AsyncMock()) as refresh,
    ):
        await entity.async_delete_todo_items(["R1", "R2"])
    assert remove.await_args_list == [call("R1"), call("R2")]
    refresh.assert_awaited_once()


async def test_delete_partial_failure_still_refreshes(hass: HomeAssistant) -> None:
    # A failure on the FIRST uid must not abort the rest of the batch: every
    # uid has to be attempted, and the refresh has to run in a `finally`, not
    # after the loop. CHECKED rows, matching the real "remove completed
    # items" card action.
    entity_id = await _setup(
        hass,
        [
            ShoppingListItem("R1", "Mjölk", True),
            ShoppingListItem("R2", "Bröd", True),
            ShoppingListItem("R3", "Ost", True),
        ],
    )
    entity = hass.data[DATA_COMPONENT].get_entity(entity_id)
    assert entity is not None
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.remove_item",
            AsyncMock(side_effect=[IcaError("boom"), None, None]),
        ) as remove,
        patch(REFRESH, AsyncMock()) as refresh,
        pytest.raises(HomeAssistantError),
    ):
        await entity.async_delete_todo_items(["R1", "R2", "R3"])
    # All three uids were attempted, not just the one that failed.
    assert remove.await_args_list == [call("R1"), call("R2"), call("R3")]
    refresh.assert_awaited_once()
