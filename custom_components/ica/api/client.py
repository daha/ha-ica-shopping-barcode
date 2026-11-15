"""ICA product and shopping-list API client (no Home Assistant imports)."""

from __future__ import annotations

import uuid
from typing import Any

import aiohttp

from .auth import IcaAuth
from .const import ARTICLE_GROUPS_URL, PRODUCT_URL, SHOPPING_LIST_BASE, USER_AGENT
from .exceptions import (
    IcaAuthError,
    IcaConnectionError,
    IcaError,
    IcaGatewayBlockedError,
)
from .models import Product, ShoppingList, ShoppingListItem


class IcaClient:
    """Async client for ICA product lookup and shopping-list operations."""

    def __init__(self, session: aiohttp.ClientSession, auth: IcaAuth) -> None:
        self._session = session
        self._auth = auth
        self._article_groups: dict[int, str] | None = None

    async def get_product(self, ean: str) -> Product | None:
        data = await self._request("GET", f"{PRODUCT_URL}/{ean}", allow_404=True)
        if data is None:
            return None
        return Product.from_api(data)

    async def get_article_groups(self) -> dict[int, str]:
        """Return the `{group id: name}` reference table, fetched once and cached.

        The table is static, so it is fetched on first use and reused for the
        life of this client. A failure returns an empty map WITHOUT caching it
        (so a later call retries): resolving a category must never fail the
        operation that asked for it.
        """
        if self._article_groups is not None:
            return self._article_groups
        try:
            data = await self._request("GET", ARTICLE_GROUPS_URL)
        except IcaError:
            return {}
        groups = (data or {}).get("articleGroups") or []
        self._article_groups = {
            group["id"]: group["name"]
            for group in groups
            if group.get("id") is not None and group.get("name")
        }
        return self._article_groups

    async def get_lists(self) -> list[ShoppingList]:
        data = await self._request("GET", f"{SHOPPING_LIST_BASE}/shoppinglists")
        return [
            ShoppingList.from_api(item)
            for item in (data or {}).get("shoppingLists") or []
        ]

    async def get_list(self, list_id: str, *, name: str | None = None) -> ShoppingList:
        """Return the list with `list_id`, falling back to a match on `name`.

        `list_id` may be an offlineId or a server id (see
        `ShoppingList.matches_id`). The name fallback lets a list configured
        against the retired web API — whose id the mobile API may not know —
        be found again; the caller can compare the result's `id` with what it
        asked for and store the new one.
        """
        lists = await self.get_lists()
        for lst in lists:
            if lst.matches_id(list_id):
                return lst
        if name:
            target = name.strip().casefold()
            for lst in lists:
                if lst.name.strip().casefold() == target:
                    return lst
        raise IcaError(f"Shopping list {list_id} not found")

    async def add_item(
        self, list_id: str, text: str, fields: dict[str, Any] | None = None
    ) -> ShoppingListItem:
        """Add a row; `fields` are extra row fields such as the article group.

        The client mints the row's offlineId, so the created row is returned
        as sent rather than parsed from the sync response.
        """
        row: dict[str, Any] = {
            **(fields or {}),
            "offlineId": str(uuid.uuid4()),
            "productName": text,
            "isStrikedOver": False,
            "sourceId": -1,
        }
        await self._sync(list_id, created=[row])
        return ShoppingListItem.from_api(row)

    async def update_item(
        self,
        list_id: str,
        item: ShoppingListItem,
        *,
        text: str | None = None,
        is_checked: bool | None = None,
    ) -> ShoppingListItem:
        """Update a row's text and/or checked state.

        A changed row is sent in full with only the requested fields changed
        — see `ShoppingListItem.to_updated_row`.
        """
        row = item.to_updated_row(text=text, is_checked=is_checked)
        await self._sync(list_id, changed=[row])
        return ShoppingListItem.from_api(row)

    async def remove_item(self, list_id: str, item_id: str) -> None:
        """Delete a row.

        A 404 is treated as success: the row is already gone, which is the
        end state the caller asked for (rows can vanish via the ICA app
        between our poll and this call).
        """
        await self._sync(list_id, deleted=[item_id], allow_404=True)

    async def _sync(
        self,
        list_id: str,
        *,
        created: list[dict[str, Any]] | None = None,
        changed: list[dict[str, Any]] | None = None,
        deleted: list[str] | None = None,
        allow_404: bool = False,
    ) -> None:
        """Apply row changes through the list's sync endpoint."""
        body = {
            "changedShoppingListProperties": {},
            "createdRows": created or [],
            "changedRows": changed or [],
            "deletedRows": deleted or [],
        }
        await self._request(
            "POST",
            f"{SHOPPING_LIST_BASE}/shoppinglists/{list_id}/sync",
            json=body,
            allow_404=allow_404,
        )

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
                    self._auth.invalidate_token()
                    return await self._request(
                        method, url, json=json, allow_404=allow_404, _retry=False
                    )
                if resp.status == 401:
                    raise IcaAuthError("ICA rejected the access token (401)")
                if resp.status == 403:
                    raise IcaGatewayBlockedError(
                        "ICA gateway returned 403 (non-Swedish IP or blocked)"
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise IcaError(f"ICA API error {resp.status}: {text}")
                if resp.status == 204:
                    return None
                body = await resp.read()
                if not body:
                    return None
                try:
                    return await resp.json()
                except ValueError as err:
                    raise IcaError(
                        f"ICA API returned a non-JSON body for {method} {url}"
                    ) from err
        except aiohttp.ClientError as err:
            raise IcaConnectionError(str(err)) from err
