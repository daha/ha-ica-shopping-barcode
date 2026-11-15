"""Typed models for the ICA mobile shopping-list API (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exceptions import IcaError


def _required(data: dict[str, Any], key: str) -> Any:
    """Return `data[key]`, mapping a malformed (missing-key) payload to IcaError."""
    try:
        return data[key]
    except KeyError as err:
        raise IcaError(f"Malformed ICA API payload: missing '{key}'") from err


@dataclass(slots=True)
class Product:
    """A product from the ICA lookup. Keeps the FULL raw payload (`raw`).

    Convenience fields are extracted for our own logic (dedupe, service
    responses), but nothing is discarded — `to_row_article()` passes the whole
    object through so store-format category data survives into the ICA list.
    Field aliases handle both the product-service (`gtin`/`articleId`) and the
    article-search (`productEan`/`id`) shapes.
    """

    name: str
    ean: str | None
    article_id: int | None
    article_group_id: int | None
    extended_article_group_id: int | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Product:
        group = data.get("articleGroupId")
        ean = data.get("gtin")
        if ean is None:
            ean = data.get("productEan")
        article_id = data.get("articleId")
        if article_id is None:
            article_id = data.get("id")
        return cls(
            name=_required(data, "name"),
            ean=ean,
            article_id=article_id,
            article_group_id=group,
            extended_article_group_id=data.get("expandedArticleGroupId", group),
            raw=dict(data),
        )

    def to_row_fields(self) -> dict[str, Any]:
        """Return the category fields for a new shopping-list row.

        The mobile shopping-list API files a row under its article group, so a
        scanned product lands in the right section of the list. Keys without a
        value are omitted.
        """
        fields: dict[str, Any] = {}
        if self.article_group_id is not None:
            fields["articleGroupId"] = self.article_group_id
        if self.extended_article_group_id is not None:
            fields["articleGroupIdExtended"] = self.extended_article_group_id
        return fields


@dataclass(slots=True)
class ShoppingListItem:
    """A single row on an ICA shopping list (mobile dialect).

    Keeps the FULL raw row: a changed row is sent back to the sync endpoint in
    its entirety, so an edit has to carry every field (see `to_updated_row`).
    """

    id: str  # row offlineId (client-generated UUID)
    text: str
    is_checked: bool
    article_group_id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ShoppingListItem:
        return cls(
            id=_required(data, "offlineId"),
            text=_required(data, "productName"),
            is_checked=bool(data.get("isStrikedOver", False)),
            article_group_id=data.get("articleGroupId"),
            raw=dict(data),
        )

    def to_updated_row(
        self, *, text: str | None = None, is_checked: bool | None = None
    ) -> dict[str, Any]:
        """Return the full row with ONLY the given fields changed.

        Everything else from the original payload passes through untouched, so
        the article group (the item's category), `internalOrder`, `sourceId`,
        `recipes` and the rest survive an edit. Omitted arguments keep the
        current value.

        The returned dict is a SHALLOW copy: nested values (`recipes`) are
        shared with this item's cached payload, so treat the result as
        read-only. Mutating them in place would corrupt the coordinator's
        snapshot until the next poll.
        """
        row = dict(self.raw)
        row.setdefault("offlineId", self.id)
        row["productName"] = self.text if text is None else text
        row["isStrikedOver"] = self.is_checked if is_checked is None else is_checked
        return row


@dataclass(slots=True)
class ShoppingList:
    """An ICA shopping list with its rows (mobile dialect)."""

    id: str  # list offlineId (client-generated UUID) — what the sync URL takes
    name: str
    items: list[ShoppingListItem] = field(default_factory=list)
    # The server-side `id`. Only used to recognise a list configured before the
    # move off the web API, whose stored id may be this rather than offlineId.
    server_id: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ShoppingList:
        rows = data.get("rows") or []
        server_id = data.get("id")
        return cls(
            id=_required(data, "offlineId"),
            name=data.get("title") or "",
            items=[ShoppingListItem.from_api(row) for row in rows],
            server_id=None if server_id is None else str(server_id),
        )

    def matches_id(self, list_id: str) -> bool:
        """True if `list_id` is this list's offlineId or its server id."""
        return list_id in (self.id, self.server_id)

    def has_active_item(self, name: str) -> bool:
        """True if an UNCHECKED row matches name (case-insensitive)."""
        target = name.strip().casefold()
        return any(
            not item.is_checked and item.text.strip().casefold() == target
            for item in self.items
        )
