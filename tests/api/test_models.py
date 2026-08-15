"""Tests for ICA API model parsing."""

from __future__ import annotations

import pytest
from custom_components.ica.api.exceptions import IcaError
from custom_components.ica.api.models import (
    Product,
    ShoppingList,
    ShoppingListItem,
)


def test_product_from_api() -> None:
    # Real product-service response (confirmed against the account).
    product = Product.from_api(
        {
            "gtin": "07318690492931",
            "consumerItemId": 2077069,
            "name": "Tvättservetter Baby Oparfymerade ICA",
            "articleId": 1006101,
            "articleGroupId": 11,
            "expandedArticleGroupId": 32,
        }
    )
    assert product.name == "Tvättservetter Baby Oparfymerade ICA"
    assert product.ean == "07318690492931"
    assert product.article_id == 1006101
    assert product.article_group_id == 11
    assert product.extended_article_group_id == 32
    # Unknown extra fields are retained for pass-through, not dropped.
    assert product.raw["consumerItemId"] == 2077069


def test_product_from_api_search_shape() -> None:
    # The alternative (article-search) shape uses `id`/`productEan`.
    product = Product.from_api(
        {
            "id": 11103,
            "name": "mjölk",
            "productEan": "7310865000293",
            "articleGroupId": 10,
        }
    )
    assert product.article_id == 11103
    assert product.ean == "7310865000293"


def test_product_to_row_article_passes_everything_through() -> None:
    # Every field from the lookup must survive — incl. store-format categories.
    raw = {
        "id": 11103,
        "name": "mjölk",
        "productEan": "7310865000293",
        "articleGroupId": 10,
        "expandedArticleGroupId": 10,
        "articleGroupName": "Mejeri",
        "maxiFormatCategoryId": "2510",
        "naraFormatCategoryName": "Mejeri/juice",
    }
    article = Product.from_api(raw).to_row_article()
    assert article["id"] == 11103
    assert article["articleGroupId"] == 10
    assert article["productEan"] == "7310865000293"
    # Store-format category fields are preserved, not dropped.
    assert article["maxiFormatCategoryId"] == "2510"
    assert article["naraFormatCategoryName"] == "Mejeri/juice"


def test_product_to_row_article_ensures_keys_when_raw_sparse() -> None:
    # Convenience-built Product (empty raw) still yields the required keys.
    product = Product("mjölk", "7310865000293", 11103, 10, 10)
    article = product.to_row_article()
    assert article["id"] == 11103
    assert article["productEan"] == "7310865000293"
    assert article["articleGroupId"] == 10
    assert article["expandedArticleGroupId"] == 10


def test_shopping_list_item_from_api() -> None:
    # Row shape as returned by GET .../list/all (names come back null).
    item = ShoppingListItem.from_api(
        {
            "id": "9e93e3cc-76c5-43f3-a31f-43e2e1754002",
            "text": "mjölk",
            "isStriked": True,
            "article": {
                "id": 11103,
                "name": None,
                "ean": None,
                "group": {"id": 10, "name": None},
                "extendedGroup": {"id": 10, "name": None},
            },
        }
    )
    assert item.id == "9e93e3cc-76c5-43f3-a31f-43e2e1754002"
    assert item.text == "mjölk"
    assert item.is_checked is True
    assert item.article_group_id == 10


def test_shopping_list_item_from_api_free_text() -> None:
    # A free-text row may still carry a server-assigned article/group.
    item = ShoppingListItem.from_api(
        {"id": "R1", "text": "Ketchup Heinz", "isStriked": False, "article": None}
    )
    assert item.text == "Ketchup Heinz"
    assert item.is_checked is False
    assert item.article_group_id is None


def test_shopping_list_from_api_with_rows() -> None:
    lst = ShoppingList.from_api(
        {
            "id": "e47ebb35-e5a9-42f2-9e37-8348dceecca4",
            "name": "Att handla",
            "rows": [
                {"id": "R1", "text": "banan", "isStriked": False},
                {"id": "R2", "text": "mjölk", "isStriked": True},
            ],
        }
    )
    assert lst.id == "e47ebb35-e5a9-42f2-9e37-8348dceecca4"
    assert lst.name == "Att handla"
    assert [i.text for i in lst.items] == ["banan", "mjölk"]
    assert lst.items[1].is_checked is True


def test_product_to_row_article_omits_keys_without_values() -> None:
    # A Product with no ids yields an article that omits those keys (not null).
    article = Product("okänt", None, None, None, None).to_row_article()
    assert "id" not in article
    assert "productEan" not in article
    assert "articleGroupId" not in article
    assert "expandedArticleGroupId" not in article


def test_shopping_list_from_api_without_rows() -> None:
    lst = ShoppingList.from_api({"id": "G1", "name": "Tom"})
    assert lst.items == []


def test_has_active_item_ignores_checked_rows() -> None:
    # C1: a struck-through ("bought") row must not shadow a re-add of the
    # same name — only UNCHECKED rows count as "active".
    lst = ShoppingList(
        id="G1",
        name="Inköpslista",
        items=[
            ShoppingListItem("R1", "Mjölk", True),
            ShoppingListItem("R2", "Bröd", False),
        ],
    )
    assert lst.has_active_item("mjölk") is False
    assert lst.has_active_item("bröd") is True


def test_has_active_item_no_match() -> None:
    lst = ShoppingList(id="G1", name="Inköpslista", items=[])
    assert lst.has_active_item("mjölk") is False


def test_product_from_api_missing_name_raises_ica_error() -> None:
    # C3: a malformed 200 must map to our own error hierarchy, not KeyError.
    with pytest.raises(IcaError):
        Product.from_api({"gtin": "123"})


def test_shopping_list_item_from_api_missing_text_raises_ica_error() -> None:
    with pytest.raises(IcaError):
        ShoppingListItem.from_api({"id": "R1", "isStriked": False})


def test_shopping_list_from_api_missing_id_raises_ica_error() -> None:
    with pytest.raises(IcaError):
        ShoppingList.from_api({"name": "Tom"})


def test_shopping_list_item_keeps_raw_row() -> None:
    row = {
        "id": "R1",
        "text": "mjölk",
        "isStriked": False,
        "order": -184,
        "quantity": None,
        "article": {"id": 11103, "group": {"id": 10}, "extendedGroup": {"id": 10}},
        "shoppingListRowId": 1030857476,
        "ingredientGroup": 1000,
    }
    item = ShoppingListItem.from_api(row)
    assert item.raw == row


def test_to_updated_row_flips_checked_and_keeps_everything_else() -> None:
    # ICA replaces the WHOLE row, so every field we received must go back —
    # dropping `article` here would destroy the item's category.
    row = {
        "id": "R1",
        "text": "mjölk",
        "isStriked": False,
        "order": -184,
        "article": {"id": 11103, "group": {"id": 10}},
        "shoppingListRowId": 1030857476,
    }
    updated = ShoppingListItem.from_api(row).to_updated_row(is_checked=True)
    assert updated["isStriked"] is True
    assert updated["text"] == "mjölk"
    assert updated["article"] == {"id": 11103, "group": {"id": 10}}
    assert updated["order"] == -184
    assert updated["shoppingListRowId"] == 1030857476


def test_to_updated_row_renames_without_touching_status() -> None:
    row = {"id": "R1", "text": "mjolk", "isStriked": True, "article": {"id": 1}}
    updated = ShoppingListItem.from_api(row).to_updated_row(text="Mjölk")
    assert updated["text"] == "Mjölk"
    assert updated["isStriked"] is True  # unchanged
    assert updated["article"] == {"id": 1}


def test_to_updated_row_defaults_to_current_values() -> None:
    row = {"id": "R1", "text": "mjölk", "isStriked": True}
    updated = ShoppingListItem.from_api(row).to_updated_row()
    assert updated["text"] == "mjölk"
    assert updated["isStriked"] is True


def test_to_updated_row_ensures_id_when_raw_is_empty() -> None:
    # A hand-built item (no raw payload) must still produce a usable row.
    updated = ShoppingListItem("R9", "Bröd", False).to_updated_row(is_checked=True)
    assert updated["id"] == "R9"
    assert updated["text"] == "Bröd"
    assert updated["isStriked"] is True
