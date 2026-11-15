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


def test_product_to_row_fields_carries_the_article_groups() -> None:
    product = Product("mjölk", "7310865000293", 11103, 10, 32)
    assert product.to_row_fields() == {
        "articleGroupId": 10,
        "articleGroupIdExtended": 32,
    }


def test_product_to_row_fields_omits_keys_without_values() -> None:
    # A Product with no group ids yields no fields (not nulls).
    assert Product("okänt", None, None, None, None).to_row_fields() == {}


def test_shopping_list_item_from_api() -> None:
    # Row shape as returned by GET .../shoppinglists.
    item = ShoppingListItem.from_api(
        {
            "id": 1030857476,
            "offlineId": "9e93e3cc-76c5-43f3-a31f-43e2e1754002",
            "productName": "mjölk",
            "isStrikedOver": True,
            "sourceId": -1,
            "internalOrder": 1,
            "articleGroupId": 10,
            "articleGroupIdExtended": 10,
            "recipes": [],
            "latestChange": "2026-10-30T18:00:00Z",
        }
    )
    assert item.id == "9e93e3cc-76c5-43f3-a31f-43e2e1754002"
    assert item.text == "mjölk"
    assert item.is_checked is True
    assert item.article_group_id == 10


def test_shopping_list_item_from_api_free_text() -> None:
    item = ShoppingListItem.from_api(
        {"offlineId": "R1", "productName": "Ketchup Heinz", "isStrikedOver": False}
    )
    assert item.text == "Ketchup Heinz"
    assert item.is_checked is False
    assert item.article_group_id is None


def test_shopping_list_from_api_with_rows() -> None:
    lst = ShoppingList.from_api(
        {
            "id": 4711,
            "offlineId": "e47ebb35-e5a9-42f2-9e37-8348dceecca4",
            "title": "Att handla",
            "commentText": "",
            "rows": [
                {"offlineId": "R1", "productName": "banan", "isStrikedOver": False},
                {"offlineId": "R2", "productName": "mjölk", "isStrikedOver": True},
            ],
        }
    )
    assert lst.id == "e47ebb35-e5a9-42f2-9e37-8348dceecca4"
    assert lst.server_id == "4711"
    assert lst.name == "Att handla"
    assert [i.text for i in lst.items] == ["banan", "mjölk"]
    assert lst.items[1].is_checked is True


def test_shopping_list_from_api_without_rows() -> None:
    lst = ShoppingList.from_api({"offlineId": "G1", "title": "Tom"})
    assert lst.items == []
    assert lst.server_id is None


def test_shopping_list_matches_offline_id_or_server_id() -> None:
    lst = ShoppingList(id="OFF1", name="A", server_id="4711")
    assert lst.matches_id("OFF1") is True
    assert lst.matches_id("4711") is True
    assert lst.matches_id("OTHER") is False


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
        ShoppingListItem.from_api({"offlineId": "R1", "isStrikedOver": False})


def test_shopping_list_from_api_missing_id_raises_ica_error() -> None:
    with pytest.raises(IcaError):
        ShoppingList.from_api({"id": 1, "title": "Tom"})


def test_shopping_list_item_keeps_raw_row() -> None:
    row = {
        "id": 1030857476,
        "offlineId": "R1",
        "productName": "mjölk",
        "isStrikedOver": False,
        "sourceId": -1,
        "internalOrder": 4,
        "articleGroupId": 10,
        "articleGroupIdExtended": 10,
        "recipes": [],
    }
    item = ShoppingListItem.from_api(row)
    assert item.raw == row


def test_to_updated_row_flips_checked_and_keeps_everything_else() -> None:
    # A changed row is sent back WHOLE, so every field we received must go
    # back — dropping the article group would destroy the item's category.
    row = {
        "id": 1030857476,
        "offlineId": "R1",
        "productName": "mjölk",
        "isStrikedOver": False,
        "internalOrder": 4,
        "articleGroupId": 10,
    }
    updated = ShoppingListItem.from_api(row).to_updated_row(is_checked=True)
    assert updated["isStrikedOver"] is True
    assert updated["productName"] == "mjölk"
    assert updated["articleGroupId"] == 10
    assert updated["internalOrder"] == 4
    assert updated["id"] == 1030857476


def test_to_updated_row_renames_without_touching_status() -> None:
    row = {"offlineId": "R1", "productName": "mjolk", "isStrikedOver": True}
    updated = ShoppingListItem.from_api(row).to_updated_row(text="Mjölk")
    assert updated["productName"] == "Mjölk"
    assert updated["isStrikedOver"] is True  # unchanged


def test_to_updated_row_defaults_to_current_values() -> None:
    row = {"offlineId": "R1", "productName": "mjölk", "isStrikedOver": True}
    updated = ShoppingListItem.from_api(row).to_updated_row()
    assert updated["productName"] == "mjölk"
    assert updated["isStrikedOver"] is True


def test_to_updated_row_ensures_id_when_raw_is_empty() -> None:
    # A hand-built item (no raw payload) must still produce a usable row.
    updated = ShoppingListItem("R9", "Bröd", False).to_updated_row(is_checked=True)
    assert updated["offlineId"] == "R9"
    assert updated["productName"] == "Bröd"
    assert updated["isStrikedOver"] is True
