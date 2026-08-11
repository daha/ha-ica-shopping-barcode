"""ICA product and web shopping-list API client (no Home Assistant imports)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiohttp

from .auth import IcaAuth
from .const import PRODUCT_URL, SHOPPING_LIST_BASE, USER_AGENT
from .exceptions import IcaConnectionError, IcaError, IcaGatewayBlockedError
from .models import Product, ShoppingList, ShoppingListItem


class IcaClient:
    """Async client for ICA product lookup and web shopping-list operations."""

    def __init__(self, session: aiohttp.ClientSession, auth: IcaAuth) -> None:
        self._session = session
        self._auth = auth

    async def get_product(self, ean: str) -> Product | None:
        data = await self._request("GET", f"{PRODUCT_URL}/{ean}", allow_404=True)
        if data is None:
            return None
        return Product.from_api(data)

    async def get_lists(self) -> list[ShoppingList]:
        data = await self._request("GET", f"{SHOPPING_LIST_BASE}/list/all")
        # The web API returns a bare JSON array of lists.
        return [ShoppingList.from_api(item) for item in (data or [])]

    async def get_list(self, list_id: str) -> ShoppingList:
        for lst in await self.get_lists():
            if lst.id == list_id:
                return lst
        raise IcaError(f"Shopping list {list_id} not found")

    async def add_item(
        self, list_id: str, text: str, article: dict[str, Any] | None = None
    ) -> ShoppingListItem:
        body: dict[str, Any] = {"isStriked": False, "quantity": {}, "text": text}
        if article is not None:
            body["article"] = article
        data = await self._request(
            "POST", f"{SHOPPING_LIST_BASE}/list/{list_id}/row", json=body
        )
        assert data is not None
        return ShoppingListItem.from_api(data)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        allow_404: bool = False,
        _retry: bool = True,
    ) -> Any:
        access = await self._auth.async_get_access_token()
        headers = {
            "Authorization": f"Bearer {access}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        try:
            async with self._session.request(
                method, url, json=json, headers=headers
            ) as resp:
                if resp.status == 404 and allow_404:
                    return None
                if resp.status == 401 and _retry:
                    token = self._auth.token
                    if token is not None:
                        # Force a refresh, then retry the request exactly once.
                        token.expires_at = datetime.now(UTC)
                    return await self._request(
                        method,
                        url,
                        json=json,
                        allow_404=allow_404,
                        _retry=False,
                    )
                if resp.status == 403:
                    raise IcaGatewayBlockedError(
                        "ICA gateway returned 403 (non-Swedish IP or blocked)"
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise IcaError(f"ICA API error {resp.status}: {text}")
                if resp.status == 204:
                    return None
                return await resp.json()
        except aiohttp.ClientError as err:
            raise IcaConnectionError(str(err)) from err
