"""Tests for ICA services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.models import Product, ShoppingList, ShoppingListItem
from custom_components.ica.const import (
    CONF_LIST_ID,
    CONF_LIST_TITLE,
    CONF_TOKEN,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
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


async def test_lookup_product_found(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with patch(
        "custom_components.ica.services.IcaClient.get_product",
        AsyncMock(return_value=Product("Mjölk", "7311041000000", 1, 10, 10)),
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "lookup_product",
            {"barcode": "7311041000000"},
            blocking=True,
            return_response=True,
        )
    assert resp == {"found": True, "name": "Mjölk", "ean": "7311041000000"}


async def test_scan_barcode_attaches_article(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with (
        patch(
            "custom_components.ica.services.IcaClient.get_product",
            AsyncMock(return_value=Product("mjölk", "7310865000293", 11103, 10, 10)),
        ),
        patch("custom_components.ica.services.IcaClient.add_item", AsyncMock()) as add,
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
        patch(
            "custom_components.ica.services.IcaClient.get_product",
            AsyncMock(return_value=None),
        ),
        patch("custom_components.ica.services.IcaClient.add_item", AsyncMock()) as add,
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
        patch("custom_components.ica.services.IcaClient.add_item", AsyncMock()) as add,
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
