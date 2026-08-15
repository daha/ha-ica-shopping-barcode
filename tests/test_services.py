"""Tests for ICA services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.exceptions import IcaAuthError, IcaGatewayBlockedError
from custom_components.ica.api.models import Product, ShoppingList, ShoppingListItem
from custom_components.ica.const import (
    CONF_LIST_ID,
    CONF_LIST_TITLE,
    CONF_TOKEN,
    DOMAIN,
    ISSUE_GATEWAY_BLOCKED,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _token_dict() -> dict[str, str]:
    return IcaToken(
        "a", "r", datetime.now(UTC) + timedelta(hours=1), "c", "s", "sc"
    ).to_dict()


async def _setup(hass: HomeAssistant, items: list[ShoppingListItem]) -> MockConfigEntry:
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
    return entry


def _patch_lists(items: list[ShoppingListItem]) -> Any:
    """Patch the FRESH `get_lists()` read every list operation now performs.

    List operations never read the coordinator's cached snapshot, so tests must
    supply the upstream state here — which is what makes the staleness
    regression test below possible.
    """
    lst = ShoppingList(id="G1", name="Inköpslista", items=items)
    return patch(
        "custom_components.ica.api.client.IcaClient.get_lists",
        AsyncMock(return_value=[lst]),
    )


async def test_lookup_product_found(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with patch(
        "custom_components.ica.api.client.IcaClient.get_product",
        # C2: the API's `gtin` (here deliberately zero-padded, i.e. different
        # from the barcode we called with) must NOT leak into the response.
        AsyncMock(return_value=Product("Mjölk", "07311041000000", 1, 10, 10)),
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "lookup_product",
            {"barcode": "7311041000000"},
            blocking=True,
            return_response=True,
        )
    # `ean` is always the INPUT barcode (C2), never `product.ean`.
    assert resp == {"found": True, "name": "Mjölk", "ean": "7311041000000"}


async def test_lookup_product_not_found_returns_input_ean(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with patch(
        "custom_components.ica.api.client.IcaClient.get_product",
        AsyncMock(return_value=None),
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "lookup_product",
            {"barcode": "999"},
            blocking=True,
            return_response=True,
        )
    assert resp == {"found": False, "name": None, "ean": "999"}


async def test_scan_barcode_attaches_article(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with (
        _patch_lists([]),
        patch(
            "custom_components.ica.api.client.IcaClient.get_product",
            AsyncMock(return_value=Product("mjölk", "7310865000293", 11103, 10, 10)),
        ),
        patch(
            "custom_components.ica.api.client.IcaClient.add_item", AsyncMock()
        ) as add,
        patch(
            "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh",
            AsyncMock(),
        ),
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "scan_barcode",
            {"barcode": "7310865000293"},
            blocking=True,
            return_response=True,
        )
    # The article (with its group ids) built from the EAN lookup is attached.
    _, kwargs = add.await_args
    assert kwargs["article"]["articleGroupId"] == 10
    assert kwargs["article"]["expandedArticleGroupId"] == 10
    assert resp == {
        "found": True,
        "added": True,
        "name": "mjölk",
        "ean": "7310865000293",
    }


async def test_scan_barcode_miss_adds_raw_ean(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with (
        _patch_lists([]),
        patch(
            "custom_components.ica.api.client.IcaClient.get_product",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.ica.api.client.IcaClient.add_item", AsyncMock()
        ) as add,
        patch(
            "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh",
            AsyncMock(),
        ),
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "scan_barcode",
            {"barcode": "999"},
            blocking=True,
            return_response=True,
        )
    add.assert_awaited_once_with("G1", "Okänd vara 999", article=None)
    assert resp == {
        "found": False,
        "added": True,
        "name": "Okänd vara 999",
        "ean": "999",
    }


async def test_add_item_dedupes(hass: HomeAssistant) -> None:
    await _setup(hass, [ShoppingListItem("R1", "Mjölk", False)])
    with (
        _patch_lists([ShoppingListItem("R1", "Mjölk", False)]),
        patch(
            "custom_components.ica.api.client.IcaClient.add_item", AsyncMock()
        ) as add,
        patch(
            "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh",
            AsyncMock(),
        ),
    ):
        resp = await hass.services.async_call(
            DOMAIN, "add_item", {"name": "mjölk"}, blocking=True, return_response=True
        )
    add.assert_not_awaited()
    assert resp == {"added": False, "name": "mjölk"}


async def test_add_item_readds_checked_off_item(hass: HomeAssistant) -> None:
    # C1: a struck-through ("bought") row must NOT block re-adding the item.
    await _setup(hass, [ShoppingListItem("R1", "Mjölk", True)])
    with (
        _patch_lists([ShoppingListItem("R1", "Mjölk", True)]),
        patch(
            "custom_components.ica.api.client.IcaClient.add_item", AsyncMock()
        ) as add,
        patch(
            "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh",
            AsyncMock(),
        ),
    ):
        resp = await hass.services.async_call(
            DOMAIN, "add_item", {"name": "mjölk"}, blocking=True, return_response=True
        )
    add.assert_awaited_once_with("G1", "mjölk", article=None)
    assert resp == {"added": True, "name": "mjölk"}


async def test_add_item_ignores_stale_cached_snapshot(hass: HomeAssistant) -> None:
    """Reported bug: `added: false` for an item removed/checked since the poll.

    The coordinator's snapshot still showed the item active, but it had been
    checked off or deleted in the ICA app since. The decision must come from a
    FRESH fetch, so the add goes through.
    """
    entry = await _setup(hass, [ShoppingListItem("R1", "Mellanmjölk ICA", False)])
    cached = entry.runtime_data.coordinator.data
    assert cached is not None
    assert (
        cached.has_active_item("mellanmjölk ica") is True
    )  # stale cache says "present"

    with (
        _patch_lists([]),  # upstream reality: it is gone
        patch(
            "custom_components.ica.api.client.IcaClient.add_item", AsyncMock()
        ) as add,
        patch(
            "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh",
            AsyncMock(),
        ),
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "add_item",
            {"name": "Mellanmjölk ICA"},
            blocking=True,
            return_response=True,
        )
    add.assert_awaited_once_with("G1", "Mellanmjölk ICA", article=None)
    assert resp == {"added": True, "name": "Mellanmjölk ICA"}


async def test_add_item_named_list_fetches_lists_once(hass: HomeAssistant) -> None:
    # S9: resolving a named list must fetch `list/all` exactly once, and must
    # NOT fall back to the old double round-trip through `get_list`.
    await _setup(hass, [])
    other_list = ShoppingList(id="G2", name="Fest", items=[])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.get_lists",
            AsyncMock(return_value=[other_list]),
        ) as get_lists,
        patch(
            "custom_components.ica.api.client.IcaClient.get_list", AsyncMock()
        ) as get_list,
        patch(
            "custom_components.ica.api.client.IcaClient.add_item", AsyncMock()
        ) as add,
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "add_item",
            {"name": "Ballonger", "list": "Fest"},
            blocking=True,
            return_response=True,
        )
    get_lists.assert_awaited_once()
    get_list.assert_not_called()
    add.assert_awaited_once_with("G2", "Ballonger", article=None)
    assert resp == {"added": True, "name": "Ballonger"}


async def test_add_item_unknown_list_raises_service_validation_error(
    hass: HomeAssistant,
) -> None:
    await _setup(hass, [])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.get_lists",
            AsyncMock(return_value=[]),
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            DOMAIN,
            "add_item",
            {"name": "Ballonger", "list": "Does not exist"},
            blocking=True,
            return_response=True,
        )


async def test_service_auth_error_triggers_reauth(hass: HomeAssistant) -> None:
    # A1: a hard 401 from the API must start the HA reauth flow, not just
    # surface a plain error.
    entry = await _setup(hass, [])
    with (
        patch.object(entry, "async_start_reauth") as start_reauth,
        patch(
            "custom_components.ica.api.client.IcaClient.get_product",
            AsyncMock(side_effect=IcaAuthError("401")),
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            DOMAIN,
            "lookup_product",
            {"barcode": "123"},
            blocking=True,
            return_response=True,
        )
    start_reauth.assert_called_once_with(hass)


async def test_service_gateway_blocked_creates_repair_issue(
    hass: HomeAssistant,
) -> None:
    # A2: a blocked gateway (403) must create the `gateway_blocked` repair
    # issue, not just surface a plain error.
    await _setup(hass, [])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.get_product",
            AsyncMock(side_effect=IcaGatewayBlockedError("403")),
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            DOMAIN,
            "lookup_product",
            {"barcode": "123"},
            blocking=True,
            return_response=True,
        )
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_GATEWAY_BLOCKED)
    assert issue is not None
