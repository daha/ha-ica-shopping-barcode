"""Tests for the ICA API client (mocked HTTP)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses
from custom_components.ica.api import const as c
from custom_components.ica.api.auth import IcaAuth, IcaToken
from custom_components.ica.api.client import IcaClient
from custom_components.ica.api.exceptions import (
    IcaAuthError,
    IcaError,
    IcaGatewayBlockedError,
)
from custom_components.ica.api.models import ShoppingListItem

LISTS_URL = f"{c.SHOPPING_LIST_BASE}/shoppinglists"


def _fresh_token() -> IcaToken:
    return IcaToken(
        "access",
        "refresh",
        datetime.now(UTC) + timedelta(hours=1),
        "cid",
        "sec",
        "scope",
    )


def _make_client(session: aiohttp.ClientSession) -> IcaClient:
    return IcaClient(session, IcaAuth(session, token=_fresh_token()))


async def test_get_product_found() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                f"{c.PRODUCT_URL}/7310865000293",
                payload={
                    "gtin": "7310865000293",
                    "name": "mjölk",
                    "articleId": 11103,
                    "articleGroupId": 10,
                    "expandedArticleGroupId": 10,
                },
            )
            product = await client.get_product("7310865000293")
    assert product is not None
    assert product.name == "mjölk"
    assert product.article_group_id == 10


async def test_get_product_not_found_returns_none() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(f"{c.PRODUCT_URL}/000", status=404)
            product = await client.get_product("000")
    assert product is None


SYNC_G1 = f"{c.SHOPPING_LIST_BASE}/shoppinglists/G1/sync"


def _lists_payload(*lists: dict[str, Any]) -> dict[str, Any]:
    return {"shoppingLists": list(lists)}


async def test_get_lists() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                LISTS_URL,
                payload=_lists_payload(
                    {
                        "id": 1,
                        "offlineId": "G1",
                        "title": "Att handla",
                        "rows": [
                            {
                                "offlineId": "R1",
                                "productName": "banan",
                                "isStrikedOver": False,
                            }
                        ],
                    },
                    {"id": 2, "offlineId": "G2", "title": "Fest", "rows": []},
                ),
            )
            lists = await client.get_lists()
    assert [x.name for x in lists] == ["Att handla", "Fest"]
    assert lists[0].id == "G1"
    assert lists[0].items[0].text == "banan"


async def test_get_list_filters_by_id() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                LISTS_URL,
                payload=_lists_payload(
                    {"offlineId": "G0", "title": "Annan", "rows": []},
                    {
                        "offlineId": "G1",
                        "title": "Att handla",
                        "rows": [
                            {
                                "offlineId": "R1",
                                "productName": "mjölk",
                                "isStrikedOver": False,
                            }
                        ],
                    },
                ),
            )
            lst = await client.get_list("G1")
    assert lst.items[0].text == "mjölk"


async def test_get_list_matches_server_id() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                LISTS_URL,
                payload=_lists_payload({"id": 4711, "offlineId": "G1", "title": "A"}),
            )
            lst = await client.get_list("4711")
    assert lst.id == "G1"


async def test_get_list_falls_back_to_name() -> None:
    # A list configured against the retired web API: its stored GUID is not
    # known to the mobile API, but the stored title still is.
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                LISTS_URL,
                payload=_lists_payload(
                    {"offlineId": "G2", "title": "Fest"},
                    {"offlineId": "G1", "title": "Att handla"},
                ),
            )
            lst = await client.get_list("OLD-WEB-GUID", name=" att HANDLA ")
    assert lst.id == "G1"


async def test_get_list_prefers_id_over_name() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                LISTS_URL,
                payload=_lists_payload(
                    {"offlineId": "G2", "title": "Att handla"},
                    {"offlineId": "G1", "title": "Omdöpt"},
                ),
            )
            lst = await client.get_list("G1", name="Att handla")
    assert lst.id == "G1"


def _capture(captured: dict[str, Any]) -> Any:
    def _cb(url: Any, **kwargs: Any) -> CallbackResult:
        captured.update(kwargs.get("json") or {})
        return CallbackResult(status=200, payload={})

    return _cb


async def test_add_item_with_fields_syncs_a_created_row() -> None:
    captured: dict[str, Any] = {}
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, callback=_capture(captured))
            item = await client.add_item(
                "G1",
                "mjölk",
                fields={"articleGroupId": 10, "articleGroupIdExtended": 32},
            )
    assert captured["changedShoppingListProperties"] == {}
    assert captured["changedRows"] == []
    assert captured["deletedRows"] == []
    (row,) = captured["createdRows"]
    assert row["productName"] == "mjölk"
    assert row["isStrikedOver"] is False
    assert row["sourceId"] == -1
    assert row["articleGroupId"] == 10
    assert row["articleGroupIdExtended"] == 32
    assert str(uuid.UUID(row["offlineId"])) == row["offlineId"]
    assert item.id == row["offlineId"]
    assert item.text == "mjölk"
    assert item.article_group_id == 10


async def test_add_item_free_text_has_no_article_group() -> None:
    captured: dict[str, Any] = {}
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, callback=_capture(captured))
            item = await client.add_item("G1", "Ketchup Heinz")
    (row,) = captured["createdRows"]
    assert "articleGroupId" not in row
    assert item.text == "Ketchup Heinz"


async def test_add_item_tolerates_empty_sync_response() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, status=204)
            item = await client.add_item("G1", "mjölk")
    assert item.text == "mjölk"


async def test_sync_error_raises_ica_error() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, status=500, body="boom")
            with pytest.raises(IcaError):
                await client.add_item("G1", "mjölk")


async def test_gateway_block_raises() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(LISTS_URL, status=403)
            with pytest.raises(IcaGatewayBlockedError):
                await client.get_lists()


async def test_get_article_groups_parses_envelope_and_caches() -> None:
    # Real shape: an {"articleGroups": [...]} envelope with lowercase keys.
    payload = {
        "articleGroups": [
            {
                "id": 10,
                "name": "Mejeri",
                "parentId": 1,
                "lastSyncDate": "2015-09-18T08:36:09",
            },
            {
                "id": 11,
                "name": "Hem & Fritid",
                "parentId": 1,
                "lastSyncDate": "2015-09-21T08:49:05",
            },
        ]
    }
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(c.ARTICLE_GROUPS_URL, payload=payload)
            first = await client.get_article_groups()
            # Only ONE response is registered, so a second HTTP request would
            # fail — proving this call is served from the cache.
            second = await client.get_article_groups()
    assert first == {10: "Mejeri", 11: "Hem & Fritid"}
    assert second == first


async def test_get_article_groups_failure_degrades_to_empty_map() -> None:
    # A category lookup must never fail the caller's operation.
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(c.ARTICLE_GROUPS_URL, status=500, body="boom")
            assert await client.get_article_groups() == {}


async def test_401_triggers_refresh_and_retry() -> None:
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session, token=_fresh_token())
        client = IcaClient(session, auth)
        with aioresponses() as mock:
            mock.get(LISTS_URL, status=401)
            mock.post(
                c.TOKEN_ENDPOINT,
                payload={
                    "access_token": "refreshed",
                    "refresh_token": "r2",
                    "expires_in": 900,
                },
            )
            mock.get(
                LISTS_URL,
                payload={
                    "shoppingLists": [{"offlineId": "G1", "title": "A", "rows": []}]
                },
            )
            lists = await client.get_lists()
    assert [x.name for x in lists] == ["A"]
    assert auth.token is not None
    assert auth.token.access_token == "refreshed"


async def test_persistent_401_raises_auth_error() -> None:
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session, token=_fresh_token())
        client = IcaClient(session, auth)
        with aioresponses() as mock:
            mock.get(LISTS_URL, status=401)
            mock.post(
                c.TOKEN_ENDPOINT,
                payload={"access_token": "r", "refresh_token": "r2", "expires_in": 900},
            )
            mock.get(LISTS_URL, status=401)
            with pytest.raises(IcaAuthError):
                await client.get_lists()


async def test_get_list_not_found_raises() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                LISTS_URL,
                payload={"shoppingLists": [{"offlineId": "OTHER", "title": "x"}]},
            )
            with pytest.raises(IcaError):
                await client.get_list("G1")


async def test_generic_server_error_raises_ica_error() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(LISTS_URL, status=500, body="boom")
            with pytest.raises(IcaError):
                await client.get_lists()


async def test_update_item_syncs_the_full_row() -> None:
    captured: dict[str, Any] = {}
    item = ShoppingListItem.from_api(
        {
            "id": 1030857476,
            "offlineId": "R1",
            "productName": "mjölk",
            "isStrikedOver": False,
            "internalOrder": 4,
            "articleGroupId": 10,
            "sourceId": -1,
        }
    )
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, callback=_capture(captured))
            result = await client.update_item("G1", item, is_checked=True)
    assert captured["createdRows"] == []
    assert captured["deletedRows"] == []
    (row,) = captured["changedRows"]
    # The whole row goes back, not just the fields we model.
    assert row == {**item.raw, "isStrikedOver": True}
    assert result.is_checked is True


async def test_update_item_renames() -> None:
    captured: dict[str, Any] = {}
    item = ShoppingListItem.from_api(
        {"offlineId": "R1", "productName": "mjolk", "isStrikedOver": False}
    )
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, callback=_capture(captured))
            result = await client.update_item("G1", item, text="Mjölk")
    (row,) = captured["changedRows"]
    assert row["productName"] == "Mjölk"
    assert row["isStrikedOver"] is False
    assert result.text == "Mjölk"


async def test_remove_item_syncs_a_deleted_row() -> None:
    captured: dict[str, Any] = {}
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, callback=_capture(captured))
            assert await client.remove_item("G1", "R1") is None
    assert captured["deletedRows"] == ["R1"]
    assert captured["createdRows"] == []
    assert captured["changedRows"] == []


async def test_remove_item_treats_404_as_success() -> None:
    # The row is already gone — that is the end state the caller wanted.
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, status=404)
            assert await client.remove_item("G1", "GONE") is None


async def test_request_empty_200_body_is_treated_as_no_content() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(SYNC_G1, status=200, body="")
            assert await client.remove_item("G1", "R1") is None
