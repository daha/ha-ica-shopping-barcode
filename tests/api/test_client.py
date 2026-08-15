"""Tests for the ICA API client (mocked HTTP)."""

from __future__ import annotations

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


async def test_get_lists() -> None:
    # GET .../list/all returns a bare JSON array of lists.
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                f"{c.SHOPPING_LIST_BASE}/list/all",
                payload=[
                    {
                        "id": "G1",
                        "name": "Att handla",
                        "rows": [{"id": "R1", "text": "banan", "isStriked": False}],
                    },
                    {"id": "G2", "name": "Fest", "rows": []},
                ],
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
                f"{c.SHOPPING_LIST_BASE}/list/all",
                payload=[
                    {
                        "id": "G1",
                        "name": "Att handla",
                        "rows": [{"id": "R1", "text": "mjölk", "isStriked": False}],
                    }
                ],
            )
            lst = await client.get_list("G1")
    assert lst.items[0].text == "mjölk"


async def test_add_item_with_article_posts_row() -> None:
    captured: dict[str, Any] = {}

    def _cb(url: Any, **kwargs: Any) -> CallbackResult:
        captured.update(kwargs.get("json") or {})
        return CallbackResult(
            status=200,
            payload={
                "id": "NEWGUID",
                "text": "mjölk",
                "isStriked": False,
                "article": {
                    "id": 11103,
                    "group": {"id": 10},
                    "extendedGroup": {"id": 10},
                },
            },
        )

    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(f"{c.SHOPPING_LIST_BASE}/list/G1/row", callback=_cb)
            item = await client.add_item(
                "G1", "mjölk", article={"id": 11103, "articleGroupId": 10}
            )
    assert captured["text"] == "mjölk"
    assert captured["isStriked"] is False
    assert captured["quantity"] == {}
    assert captured["article"]["articleGroupId"] == 10
    assert item.text == "mjölk"
    assert item.article_group_id == 10


async def test_add_item_free_text_omits_article() -> None:
    captured: dict[str, Any] = {}

    def _cb(url: Any, **kwargs: Any) -> CallbackResult:
        captured.update(kwargs.get("json") or {})
        return CallbackResult(
            status=200, payload={"id": "G", "text": "Ketchup Heinz", "isStriked": False}
        )

    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(f"{c.SHOPPING_LIST_BASE}/list/G1/row", callback=_cb)
            item = await client.add_item("G1", "Ketchup Heinz")
    assert "article" not in captured
    assert item.text == "Ketchup Heinz"


async def test_add_item_no_content_raises_ica_error() -> None:
    # S12: the internal guard (formerly a bare `assert`) raises IcaError.
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.post(f"{c.SHOPPING_LIST_BASE}/list/G1/row", status=204)
            with pytest.raises(IcaError):
                await client.add_item("G1", "mjölk")


async def test_gateway_block_raises() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(f"{c.SHOPPING_LIST_BASE}/list/all", status=403)
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
            mock.get(f"{c.SHOPPING_LIST_BASE}/list/all", status=401)
            mock.post(
                c.TOKEN_ENDPOINT,
                payload={
                    "access_token": "refreshed",
                    "refresh_token": "r2",
                    "expires_in": 900,
                },
            )
            mock.get(
                f"{c.SHOPPING_LIST_BASE}/list/all",
                payload=[{"id": "G1", "name": "A", "rows": []}],
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
            mock.get(f"{c.SHOPPING_LIST_BASE}/list/all", status=401)
            mock.post(
                c.TOKEN_ENDPOINT,
                payload={"access_token": "r", "refresh_token": "r2", "expires_in": 900},
            )
            mock.get(f"{c.SHOPPING_LIST_BASE}/list/all", status=401)
            with pytest.raises(IcaAuthError):
                await client.get_lists()


async def test_get_list_not_found_raises() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                f"{c.SHOPPING_LIST_BASE}/list/all",
                payload=[{"id": "OTHER", "name": "x", "rows": []}],
            )
            with pytest.raises(IcaError):
                await client.get_list("G1")


async def test_generic_server_error_raises_ica_error() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(f"{c.SHOPPING_LIST_BASE}/list/all", status=500, body="boom")
            with pytest.raises(IcaError):
                await client.get_lists()


async def test_update_item_puts_the_full_row() -> None:
    captured: dict[str, Any] = {}

    def _cb(url: Any, **kwargs: Any) -> CallbackResult:
        captured.update(kwargs.get("json") or {})
        return CallbackResult(
            status=200,
            payload={
                "id": "R1",
                "text": "mjölk",
                "isStriked": True,
                "article": {"id": 11103, "group": {"id": 10}},
            },
        )

    item = ShoppingListItem.from_api(
        {
            "id": "R1",
            "text": "mjölk",
            "isStriked": False,
            "order": -184,
            "article": {"id": 11103, "group": {"id": 10}},
            "shoppingListRowId": 1030857476,
        }
    )
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.put(f"{c.SHOPPING_LIST_BASE}/row/R1", callback=_cb)
            result = await client.update_item(item, is_checked=True)
    # The whole row goes back, not just the fields we model.
    assert captured["isStriked"] is True
    assert captured["article"] == {"id": 11103, "group": {"id": 10}}
    assert captured["order"] == -184
    assert captured["shoppingListRowId"] == 1030857476
    assert result.is_checked is True


async def test_update_item_renames() -> None:
    captured: dict[str, Any] = {}

    def _cb(url: Any, **kwargs: Any) -> CallbackResult:
        captured.update(kwargs.get("json") or {})
        return CallbackResult(
            status=200, payload={"id": "R1", "text": "Mjölk", "isStriked": False}
        )

    item = ShoppingListItem.from_api({"id": "R1", "text": "mjolk", "isStriked": False})
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.put(f"{c.SHOPPING_LIST_BASE}/row/R1", callback=_cb)
            result = await client.update_item(item, text="Mjölk")
    assert captured["text"] == "Mjölk"
    assert captured["isStriked"] is False
    assert result.text == "Mjölk"


async def test_remove_item_deletes_the_row() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.delete(f"{c.SHOPPING_LIST_BASE}/row/R1", status=204)
            assert await client.remove_item("R1") is None


async def test_remove_item_treats_404_as_success() -> None:
    # The row is already gone — that is the end state the caller wanted.
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.delete(f"{c.SHOPPING_LIST_BASE}/row/GONE", status=404)
            assert await client.remove_item("GONE") is None


async def test_request_empty_200_body_is_treated_as_no_content() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.delete(f"{c.SHOPPING_LIST_BASE}/row/R1", status=200, body="")
            assert await client.remove_item("R1") is None
