"""Typed models for the ICA web shopping-list API (no Home Assistant imports)."""

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

    def to_row_article(self) -> dict[str, Any]:
        """Return the full `article` object for an add-row request.

        Passes through EVERY field from the lookup (store-format categories,
        group names, etc.) and ensures the keys the add endpoint needs
        (`id`, `productEan`, `articleGroupId`, `expandedArticleGroupId`) are
        present whenever we have a value for them — never overriding what the
        payload already carries.
        """
        article = dict(self.raw)
        if self.article_id is not None:
            article.setdefault("id", self.article_id)
        if self.ean is not None:
            article.setdefault("productEan", self.ean)
        if self.article_group_id is not None:
            article.setdefault("articleGroupId", self.article_group_id)
        if self.extended_article_group_id is not None:
            article.setdefault("expandedArticleGroupId", self.extended_article_group_id)
        return article


@dataclass(slots=True)
class ShoppingListItem:
    """A single row on an ICA shopping list (web dialect).

    Keeps the FULL raw row: ICA's update endpoint REPLACES the row, so an edit
    has to send every field back (see `to_updated_row`).
    """

    id: str  # row GUID
    text: str
    is_checked: bool
    article_group_id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ShoppingListItem:
        article = data.get("article") or {}
        group = article.get("group") or {}
        return cls(
            id=_required(data, "id"),
            text=_required(data, "text"),
            is_checked=bool(data.get("isStriked", False)),
            article_group_id=group.get("id"),
            raw=dict(data),
        )

    def to_updated_row(
        self, *, text: str | None = None, is_checked: bool | None = None
    ) -> dict[str, Any]:
        """Return the full row with ONLY the given fields changed.

        Everything else from the original payload passes through untouched, so
        `article` (the item's category), `order`, `quantity`, `created` and the
        rest survive an edit. Omitted arguments keep the current value.

        The returned dict is a SHALLOW copy: nested values (`article`,
        `quantity`) are shared with this item's cached payload, so treat the
        result as read-only. Mutating them in place would corrupt the
        coordinator's snapshot until the next poll.
        """
        row = dict(self.raw)
        row.setdefault("id", self.id)
        row["text"] = self.text if text is None else text
        row["isStriked"] = self.is_checked if is_checked is None else is_checked
        return row


@dataclass(slots=True)
class ShoppingList:
    """An ICA shopping list with its rows (web dialect)."""

    id: str  # list GUID
    name: str
    items: list[ShoppingListItem] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ShoppingList:
        rows = data.get("rows") or []
        return cls(
            id=_required(data, "id"),
            name=data.get("name", ""),
            items=[ShoppingListItem.from_api(row) for row in rows],
        )

    def has_active_item(self, name: str) -> bool:
        """True if an UNCHECKED row matches name (case-insensitive)."""
        target = name.strip().casefold()
        return any(
            not item.is_checked and item.text.strip().casefold() == target
            for item in self.items
        )
