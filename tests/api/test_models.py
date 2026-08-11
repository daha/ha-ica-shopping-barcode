"""Tests for ICA API model parsing."""

from __future__ import annotations

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
        {"id": 11103, "name": "mjölk", "productEan": "7310865000293", "articleGroupId": 10}
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
