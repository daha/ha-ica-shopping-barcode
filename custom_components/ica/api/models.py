"""Typed models for the ICA web shopping-list API (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    def from_api(cls, data: dict[str, Any]) -> "Product":
        # `expandedArticleGroupId` falls back to `articleGroupId` when absent.
        group = data.get("articleGroupId")
        return cls(
            name=data["name"],
            ean=data.get("gtin") or data.get("productEan"),
            article_id=data.get("articleId") or data.get("id"),
            article_group_id=group,
            extended_article_group_id=data.get("expandedArticleGroupId", group),
            raw=data,
        )

    def to_row_article(self) -> dict[str, Any]:
        """Return the full `article` object for an add-row request.

        Passes through EVERY field from the lookup (store-format categories,
        group names, etc.) and only *ensures* the keys the add endpoint needs
        (`id`, `productEan`, `articleGroupId`, `expandedArticleGroupId`) are
        present — never overriding what the payload already carries.
        """
        article = dict(self.raw)
        article.setdefault("id", self.article_id)
        article.setdefault("productEan", self.ean)
        if self.article_group_id is not None:
            article.setdefault("articleGroupId", self.article_group_id)
        if self.extended_article_group_id is not None:
            article.setdefault(
                "expandedArticleGroupId", self.extended_article_group_id
            )
        return article


@dataclass(slots=True)
class ShoppingListItem:
    """A single row on an ICA shopping list (web dialect)."""

    id: str  # row GUID
    text: str
    is_checked: bool
    article_group_id: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "ShoppingListItem":
        article = data.get("article") or {}
        group = article.get("group") or {}
        return cls(
            id=data["id"],
            text=data["text"],
            is_checked=bool(data.get("isStriked", False)),
            article_group_id=group.get("id"),
        )


@dataclass(slots=True)
class ShoppingList:
    """An ICA shopping list with its rows (web dialect)."""

    id: str  # list GUID
    name: str
    items: list[ShoppingListItem] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "ShoppingList":
        rows = data.get("rows") or []
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            items=[ShoppingListItem.from_api(row) for row in rows],
        )
