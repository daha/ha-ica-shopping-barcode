# ICA Integration — Phase 1 (Barcode Lookup + Add-to-List Services) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-installable Home Assistant custom integration (`ica`) that authenticates to ICA and exposes three services — `ica.lookup_product`, `ica.add_item`, `ica.scan_barcode` — so an ESP32/ESPHome barcode scanner can look up an EAN and add the product to the household's ICA shopping list.

**Architecture:** A HA-free async ICA API client (`custom_components/ica/api/`) handles OAuth2/DCR/PKCE auth and the ICA product + shopping-list endpoints. A thin HA layer (config flow, coordinator, services) wraps it. The config flow authenticates and lets the user pick a default list; a `DataUpdateCoordinator` polls that list so the "merge, no count" dedupe check reads from memory. Phase 2 (a `TodoListEntity`) is a separate plan.

**Tech Stack:** Python 3.13, `aiohttp` (provided by Home Assistant), Home Assistant 2025.1+ (dev deps resolve to the latest), `uv` (dev deps), `ruff` (lint+format), `mypy` (typing), `pytest` + `pytest-homeassistant-custom-component` + `aioresponses` (tests), `pre-commit`, GitHub Actions CI.

## Global Constraints

- **Domain string is exactly `ica`** — used verbatim in `manifest.json`, folder name `custom_components/ica/`, and every service/entity namespace.
- **Python 3.13+**; target **Home Assistant 2025.1.0** minimum (dev deps resolve to the latest 2026 release via `uv`).
- **`manifest.json` `requirements` MUST stay `[]`.** The API client uses only `aiohttp` (HA-provided) and stdlib (`base64`, `hashlib`, `secrets`, `re`, `uuid`, `datetime`, `json`). No new runtime PyPI deps.
- **`custom_components/ica/api/` MUST NOT import from `homeassistant`** — it stays a pure Python package so it is unit-testable without HA and extractable later.
- **UI text:** English is the source (`strings.json` + `translations/en.json`); Swedish in `translations/sv.json`. **Shopping-list item text stays Swedish** (product name from ICA, or the raw-EAN label). Code and comments in English.
- **Unknown-item label:** when an EAN is not found, the list item text is `Okänd vara <ean>` (Swedish for "Unknown item").
- **Dedupe = "merge, no count":** before adding, compare the candidate item text case-insensitively against current list item names; add only if absent.
- **All new code fully type-annotated**, passes `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, and `uv run pytest`.
- **Credit upstream** (`kanylbullen/ica-mcp`, `LazyTarget/ha-ica-todo`, both MIT) in `README.md` and a `NOTICE` file.
- **`codeowners`/GitHub URLs** use the placeholder handle `@davidhaglund` and repo `barcode-ica-shopping-list`; replace the handle with the real GitHub username if different (config value, set once in Task 1).
- Commit after every task's tests pass.

---

### Task 1: Repo scaffold & dev tooling

Sets up the dual-natured repo (uv dev project wrapping a HA integration package) and all quality gates so every later task can run `ruff`/`mypy`/`pytest`.

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.pre-commit-config.yaml`
- Create: `.github/workflows/validate.yml`
- Create: `hacs.json`
- Create: `README.md`
- Create: `NOTICE`
- Create: `custom_components/ica/__init__.py` (empty placeholder, replaced in Task 5)
- Create: `tests/__init__.py`
- Create: `tests/test_scaffold.py`

**Interfaces:**
- Consumes: nothing.
- Produces: working `uv` env; commands `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy custom_components`, `uv run pytest`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "ha-ica-shopping"
version = "0.1.0"
description = "Home Assistant integration for ICA shopping list with barcode scanning"
requires-python = ">=3.13"
dependencies = []

[dependency-groups]
dev = [
    "homeassistant>=2025.1.0",
    "pytest>=8.0",
    "pytest-homeassistant-custom-component",
    "aioresponses>=0.7.6",
    "ruff>=0.6.0",
    "mypy>=1.11",
]

[tool.ruff]
target-version = "py313"
line-length = 88
src = ["custom_components", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "ASYNC"]

[tool.mypy]
python_version = "3.13"
strict = true
warn_unused_ignores = true
disallow_untyped_defs = true
files = ["custom_components/ica"]

[[tool.mypy.overrides]]
module = ["aioresponses.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/
*.egg-info/
.coverage
htmlcov/
```

- [ ] **Step 3: Create `hacs.json`**

```json
{
  "name": "ICA Shopping List",
  "render_readme": true,
  "homeassistant": "2025.1.0"
}
```

> `pytest-homeassistant-custom-component` is intentionally left unpinned so `uv` resolves the release matching the latest Home Assistant it pulls in; `uv.lock` captures the exact versions.

- [ ] **Step 4: Create `custom_components/ica/__init__.py`** (temporary placeholder; replaced in Task 5)

```python
"""ICA Shopping List integration."""
```

- [ ] **Step 5: Create `tests/__init__.py`** (empty file) and **`tests/test_scaffold.py`**

```python
"""Smoke test proving the toolchain runs."""


def test_toolchain_runs() -> None:
    assert True
```

- [ ] **Step 6: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: uv run mypy custom_components/ica
        language: system
        types: [python]
        pass_filenames: false
      - id: pytest
        name: pytest
        entry: uv run pytest
        language: system
        types: [python]
        pass_filenames: false
        stages: [pre-push]
```

- [ ] **Step 7: Create `.github/workflows/validate.yml`**

```yaml
name: Validate
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --group dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy custom_components/ica
      - run: uv run pytest

  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master

  hacs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hacs/action@main
        with:
          category: integration
```

- [ ] **Step 8: Create `README.md`** (skeleton with upstream credit)

```markdown
# ICA Shopping List (Home Assistant)

A custom Home Assistant integration that looks up scanned barcodes (EAN/GTIN)
against ICA and adds products to your ICA shopping list. Designed to be driven by
an ESP32 + barcode scanner running ESPHome.

## Status
Phase 1: services `ica.lookup_product`, `ica.add_item`, `ica.scan_barcode`.

## Requirements
- An ICA account with password login (not BankID-only).
- Home Assistant reachable from a Swedish IP (ICA's API blocks non-Swedish IPs).

## Credits
Auth and API approach ported from [kanylbullen/ica-mcp](https://github.com/kanylbullen/ica-mcp)
and [LazyTarget/ha-ica-todo](https://github.com/LazyTarget/ha-ica-todo) (both MIT). See `NOTICE`.
```

- [ ] **Step 9: Create `NOTICE`**

```text
This project ports authentication and API-client logic from:
- kanylbullen/ica-mcp (MIT License)
- LazyTarget/ha-ica-todo (MIT License)
```

- [ ] **Step 10: Initialise the uv environment and run the gates**

Run:
```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```
Expected: `uv sync` creates `.venv` and `uv.lock`; ruff reports no errors; pytest shows `1 passed`.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml uv.lock .gitignore hacs.json .pre-commit-config.yaml \
  .github README.md NOTICE custom_components tests
git commit -m "chore: scaffold repo, tooling, and CI"
```

---

### Task 2: API constants, exceptions, and models

The HA-free data layer: endpoint constants, the exception hierarchy, and typed models that parse ICA's JSON shapes.

**Files:**
- Create: `custom_components/ica/api/__init__.py`
- Create: `custom_components/ica/api/const.py`
- Create: `custom_components/ica/api/exceptions.py`
- Create: `custom_components/ica/api/models.py`
- Test: `tests/api/__init__.py`, `tests/api/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Constants: `IMS_BASE`, `API_BASE`, `TOKEN_ENDPOINT`, `AUTHORIZE_ENDPOINT`, `REGISTER_ENDPOINT`, `LOGIN_ENDPOINT`, `DCR_CLIENT_ID`, `DCR_CLIENT_SECRET`, `DCR_SOFTWARE_ID`, `REDIRECT_URI`, `ACR`, `USER_AGENT`, `SHOPPING_LIST_BASE` (web shopping-list API base), `ARTICLE_SEARCH_URL` (article autocomplete), `PRODUCT_URL` (product-service base).
  - Exceptions: `IcaError`, `IcaAuthError`, `IcaConnectionError`, `IcaGatewayBlockedError`.
  - Models (web dialect):
    - `Product(name: str, ean: str | None, article_id: int | None, article_group_id: int | None, extended_article_group_id: int | None)` with `from_api(dict) -> Product` (parses product-service keys `name`, `gtin`, `articleId`, `articleGroupId`, `expandedArticleGroupId`); method `to_row_article() -> dict` building the `article` object for an add request.
    - `ShoppingListItem(id: str, text: str, is_checked: bool, article_group_id: int | None)` with `from_api(dict)` (parses row keys `id`, `text`, `isStriked`, nested `article.group.id`).
    - `ShoppingList(id: str, name: str, items: list[ShoppingListItem])` with `from_api(dict)` (parses list keys `id`, `name`, `rows`).

- [ ] **Step 1: Create `custom_components/ica/api/const.py`**

```python
"""Constants for the ICA API client (no Home Assistant imports)."""

from __future__ import annotations

IMS_BASE = "https://ims.icagruppen.se"
API_BASE = "https://apimgw-pub.ica.se"

TOKEN_ENDPOINT = f"{IMS_BASE}/oauth/v2/token"
AUTHORIZE_ENDPOINT = f"{IMS_BASE}/oauth/v2/authorize"
REGISTER_ENDPOINT = f"{IMS_BASE}/register"
LOGIN_ENDPOINT = f"{IMS_BASE}/authn/authenticate/IcaCustomers"

DCR_CLIENT_ID = "ica-app-dcr-registration"
DCR_CLIENT_SECRET = "uxLHTBvZ-Z2fV-SbrHl1E-tz7vB3jQFrwAdSLlbVMMu1rxDdvJU0s8KGu9d1wLS4"
DCR_SOFTWARE_ID = "dcr-ica-app-template"

REDIRECT_URI = "icacurity://app"
ACR = "urn:se:curity:authentication:html-form:IcaCustomers"

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15"
)

# Web shopping-list service (ica.se) — the API our account actually uses.
#   list all:   GET    {SHOPPING_LIST_BASE}/list/all
#   add row:    POST   {SHOPPING_LIST_BASE}/list/{list_id}/row
#   update row: PUT    {SHOPPING_LIST_BASE}/row/{row_id}     (Phase 2: check/uncheck; body = full row)
#   delete row: DELETE {SHOPPING_LIST_BASE}/row/{row_id}     (Phase 2: no body)
SHOPPING_LIST_BASE = f"{API_BASE}/sverige/digx/shopping-list/v1/api"
# Article search (autocomplete used before adding) — GET {ARTICLE_SEARCH_URL}?query=<q>
ARTICLE_SEARCH_URL = f"{API_BASE}/sverige/digx/shoppinglistarticlesearch/v1/search"
# Product service (EAN/GTIN lookup) — GET {PRODUCT_URL}/{ean}
PRODUCT_URL = f"{API_BASE}/sverige/digx/mobile/productservice/v1/product"
```

- [ ] **Step 2: Create `custom_components/ica/api/exceptions.py`**

```python
"""Exceptions raised by the ICA API client."""

from __future__ import annotations


class IcaError(Exception):
    """Base error for all ICA client failures."""


class IcaAuthError(IcaError):
    """Authentication failed (bad credentials or unrecoverable token error)."""


class IcaConnectionError(IcaError):
    """Network or transport error talking to ICA."""


class IcaGatewayBlockedError(IcaConnectionError):
    """ICA's API gateway rejected the request (likely a non-Swedish IP)."""
```

- [ ] **Step 3: Write the failing test — `tests/api/__init__.py`** (empty) and **`tests/api/test_models.py`**

```python
"""Tests for ICA API model parsing."""

from __future__ import annotations

from custom_components.ica.api.models import (
    Product,
    ShoppingList,
    ShoppingListItem,
)


def test_product_from_api() -> None:
    product = Product.from_api(
        {
            "gtin": "7310865000293",
            "name": "mjölk",
            "articleId": 11103,
            "articleGroupId": 10,
            "expandedArticleGroupId": 10,
        }
    )
    assert product.name == "mjölk"
    assert product.ean == "7310865000293"
    assert product.article_id == 11103
    assert product.article_group_id == 10
    assert product.extended_article_group_id == 10


def test_product_to_row_article() -> None:
    product = Product.from_api(
        {
            "gtin": "7310865000293",
            "name": "mjölk",
            "articleId": 11103,
            "articleGroupId": 10,
            "expandedArticleGroupId": 10,
        }
    )
    article = product.to_row_article()
    assert article["id"] == 11103
    assert article["articleGroupId"] == 10
    assert article["expandedArticleGroupId"] == 10
    assert article["productEan"] == "7310865000293"


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
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/api/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: custom_components.ica.api.models`.

- [ ] **Step 5: Create `custom_components/ica/api/models.py`**

```python
"""Typed models for the ICA web shopping-list API (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Product:
    """A product returned by the ICA product service (EAN lookup)."""

    name: str
    ean: str | None
    article_id: int | None
    article_group_id: int | None
    extended_article_group_id: int | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Product":
        # `expandedArticleGroupId` falls back to `articleGroupId` when absent.
        group = data.get("articleGroupId")
        return cls(
            name=data["name"],
            ean=data.get("gtin"),
            article_id=data.get("articleId"),
            article_group_id=group,
            extended_article_group_id=data.get("expandedArticleGroupId", group),
        )

    def to_row_article(self) -> dict[str, Any]:
        """Build the `article` object for an add-row request.

        Carries the group ids so ICA files the row in the correct category.
        """
        return {
            "id": self.article_id,
            "name": self.name,
            "productEan": self.ean,
            "articleGroupId": self.article_group_id,
            "expandedArticleGroupId": self.extended_article_group_id,
        }


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
```

- [ ] **Step 6: Create `custom_components/ica/api/__init__.py`** (re-exports)

```python
"""HA-free ICA API client package."""

from __future__ import annotations

from .exceptions import (
    IcaAuthError,
    IcaConnectionError,
    IcaError,
    IcaGatewayBlockedError,
)
from .models import Product, ShoppingList, ShoppingListItem

__all__ = [
    "IcaAuthError",
    "IcaConnectionError",
    "IcaError",
    "IcaGatewayBlockedError",
    "Product",
    "ShoppingList",
    "ShoppingListItem",
]
```

- [ ] **Step 7: Run tests + type check**

Run: `uv run pytest tests/api/test_models.py -v && uv run mypy custom_components/ica`
Expected: tests PASS; mypy `Success`.

- [ ] **Step 8: Commit**

```bash
git add custom_components/ica/api tests/api
git commit -m "feat(api): add ICA constants, exceptions, and typed models"
```

---

### Task 3: Authentication (`api/auth.py`)

Ports the six-step OAuth2/DCR/PKCE + personnummer/password flow and token refresh. **This is the highest-risk task**: cross-check every request against the upstream file `https://raw.githubusercontent.com/kanylbullen/ica-mcp/main/ica_mcp/client.py`. Unit tests pin the intended request shapes with mocked HTTP; the definitive validation is the manual smoke test in Task 8.

**Files:**
- Create: `custom_components/ica/api/auth.py`
- Test: `tests/api/test_auth.py`

**Interfaces:**
- Consumes: `const.py` constants; `IcaAuthError`, `IcaConnectionError`.
- Produces:
  - `IcaToken` dataclass: `access_token: str`, `refresh_token: str`, `expires_at: datetime`, `client_id: str`, `client_secret: str`, `scope: str`; property `is_expired: bool`; `to_dict() -> dict[str, str]`; classmethod `from_dict(dict) -> IcaToken`.
  - `IcaAuth(session: aiohttp.ClientSession, token: IcaToken | None = None, token_updated: Callable[[IcaToken], Awaitable[None]] | None = None)`:
    - `async login(personnummer: str, password: str) -> IcaToken`
    - `async async_get_access_token() -> str` (refreshes if expired; calls `token_updated`)
    - property `token -> IcaToken | None`

- [ ] **Step 1: Write the failing test — `tests/api/test_auth.py`**

```python
"""Tests for the ICA authentication flow (mocked HTTP)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.ica.api import const as c
from custom_components.ica.api.auth import IcaAuth, IcaToken


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=1)


def test_token_is_expired() -> None:
    fresh = IcaToken("a", "r", _future(), "cid", "sec", "scope")
    stale = IcaToken("a", "r", _past(), "cid", "sec", "scope")
    assert fresh.is_expired is False
    assert stale.is_expired is True


def test_token_roundtrip() -> None:
    token = IcaToken("a", "r", _future(), "cid", "sec", "scope")
    assert IcaToken.from_dict(token.to_dict()) == token


async def test_async_get_access_token_refreshes_when_expired() -> None:
    updated: list[IcaToken] = []

    async def on_update(tok: IcaToken) -> None:
        updated.append(tok)

    stale = IcaToken("old", "refresh-me", _past(), "cid", "sec", "scope")
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session, token=stale, token_updated=on_update)
        with aioresponses() as mock:
            mock.post(
                c.TOKEN_ENDPOINT,
                payload={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 900,
                },
            )
            access = await auth.async_get_access_token()

    assert access == "new-access"
    assert auth.token is not None
    assert auth.token.refresh_token == "new-refresh"
    assert updated and updated[-1].access_token == "new-access"


async def test_async_get_access_token_returns_cached_when_fresh() -> None:
    fresh = IcaToken("cached", "r", _future(), "cid", "sec", "scope")
    async with aiohttp.ClientSession() as session:
        auth = IcaAuth(session, token=fresh)
        access = await auth.async_get_access_token()
    assert access == "cached"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/api/test_auth.py -v`
Expected: FAIL — cannot import `IcaAuth`/`IcaToken`.

- [ ] **Step 3: Create `custom_components/ica/api/auth.py`**

> Cross-check request construction against upstream `ica_mcp/client.py`. Keep the six steps in order; they share cookies via the one `aiohttp.ClientSession`.

```python
"""ICA authentication: OAuth2 + dynamic client registration + PKCE + login.

Ported from kanylbullen/ica-mcp (MIT) and LazyTarget/ha-ica-todo (MIT).
This module MUST NOT import from `homeassistant`.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

from .const import (
    ACR,
    AUTHORIZE_ENDPOINT,
    DCR_CLIENT_ID,
    DCR_CLIENT_SECRET,
    DCR_SOFTWARE_ID,
    LOGIN_ENDPOINT,
    REDIRECT_URI,
    REGISTER_ENDPOINT,
    TOKEN_ENDPOINT,
    USER_AGENT,
)
from .exceptions import IcaAuthError, IcaConnectionError

_EXPIRY_MARGIN = timedelta(seconds=60)
_TOKEN_RE = re.compile(r'name="token"[^>]*value="([^"]+)"')


@dataclass
class IcaToken:
    """A cached ICA token bundle plus the dynamic client credentials."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    client_id: str
    client_secret: str
    scope: str

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= (self.expires_at - _EXPIRY_MARGIN)

    def to_dict(self) -> dict[str, str]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "IcaToken":
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scope=data["scope"],
        )


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    verifier = re.sub(r"[^a-zA-Z0-9]", "", verifier)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _query_value(location: str, key: str) -> str:
    parsed = urlparse(location)
    values = parse_qs(parsed.query).get(key)
    if not values:
        raise IcaAuthError(f"Missing '{key}' in redirect: {location}")
    return values[0]


class IcaAuth:
    """Performs and refreshes ICA authentication over one aiohttp session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: IcaToken | None = None,
        token_updated: Callable[[IcaToken], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._token = token
        self._token_updated = token_updated

    @property
    def token(self) -> IcaToken | None:
        return self._token

    async def async_get_access_token(self) -> str:
        if self._token is None:
            raise IcaAuthError("Not authenticated; call login() first")
        if self._token.is_expired:
            await self._refresh()
        return self._token.access_token

    async def login(self, personnummer: str, password: str) -> IcaToken:
        try:
            # Step 1: bootstrap client-credentials token (scope=dcr).
            bootstrap = await self._post_form(
                TOKEN_ENDPOINT,
                {
                    "client_id": DCR_CLIENT_ID,
                    "client_secret": DCR_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                    "scope": "dcr",
                    "response_type": "token",
                },
            )
            # Step 2: dynamic client registration.
            reg = await self._post_json(
                REGISTER_ENDPOINT,
                {"software_id": DCR_SOFTWARE_ID},
                headers={"Authorization": f"Bearer {bootstrap['access_token']}"},
            )
            client_id = reg["client_id"]
            client_secret = reg["client_secret"]
            scope = reg["scope"]

            # Step 3: authorize (PKCE) -> capture state from redirect.
            verifier, challenge = _pkce_pair()
            state = await self._authorize_get(client_id, scope, challenge)

            # Step 4: post credentials -> extract SSO token from HTML form.
            sso_token = await self._login_form(personnummer, password)

            # Step 5: authorize with SSO token + state -> capture code.
            code = await self._authorize_post(client_id, sso_token, state)

            # Step 6: exchange code for access/refresh tokens.
            tok = await self._post_form(
                TOKEN_ENDPOINT,
                {
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "scope": scope,
                    "response_type": "token",
                    "code_verifier": verifier,
                    "redirect_uri": REDIRECT_URI,
                },
            )
        except aiohttp.ClientError as err:
            raise IcaConnectionError(str(err)) from err

        token = IcaToken(
            access_token=tok["access_token"],
            refresh_token=tok["refresh_token"],
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=int(tok["expires_in"])),
            client_id=client_id,
            client_secret=client_secret,
            scope=scope,
        )
        self._token = token
        await self._notify(token)
        return token

    async def _refresh(self) -> None:
        assert self._token is not None
        basic = base64.b64encode(
            f"{self._token.client_id}:{self._token.client_secret}".encode()
        ).decode()
        try:
            data = await self._post_form(
                TOKEN_ENDPOINT,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": self._token.refresh_token,
                },
                headers={"Authorization": f"Basic {basic}"},
            )
        except aiohttp.ClientError as err:
            raise IcaConnectionError(str(err)) from err
        self._token = IcaToken(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", self._token.refresh_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=int(data["expires_in"])),
            client_id=self._token.client_id,
            client_secret=self._token.client_secret,
            scope=self._token.scope,
        )
        await self._notify(self._token)

    async def _notify(self, token: IcaToken) -> None:
        if self._token_updated is not None:
            await self._token_updated(token)

    async def _authorize_get(self, client_id: str, scope: str, challenge: str) -> str:
        params = {
            "client_id": client_id,
            "scope": scope,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "login",
            "acr": ACR,
        }
        async with self._session.get(
            AUTHORIZE_ENDPOINT,
            params=params,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=False,
        ) as resp:
            location = resp.headers.get("Location", "")
        return _query_value(location, "state")

    async def _login_form(self, personnummer: str, password: str) -> str:
        async with self._session.post(
            LOGIN_ENDPOINT,
            data={"userName": personnummer, "password": password},
            headers={"User-Agent": USER_AGENT},
        ) as resp:
            html = await resp.text()
            if resp.status >= 400:
                raise IcaAuthError("Invalid personnummer or password")
        match = _TOKEN_RE.search(html)
        if not match:
            raise IcaAuthError("Login failed: no SSO token in response")
        return match.group(1)

    async def _authorize_post(self, client_id: str, sso_token: str, state: str) -> str:
        async with self._session.post(
            AUTHORIZE_ENDPOINT,
            params={"client_id": client_id, "forceAuthN": "true", "acr": ACR},
            data={"token": sso_token, "state": state},
            headers={"User-Agent": USER_AGENT},
            allow_redirects=False,
        ) as resp:
            location = resp.headers.get("Location", "")
        return _query_value(location, "code")

    async def _post_form(
        self,
        url: str,
        data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged = {"User-Agent": USER_AGENT, **(headers or {})}
        async with self._session.post(url, data=data, headers=merged) as resp:
            payload: dict[str, Any] = await resp.json()
            return payload

    async def _post_json(
        self,
        url: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged = {"User-Agent": USER_AGENT, **(headers or {})}
        async with self._session.post(url, json=data, headers=merged) as resp:
            payload: dict[str, Any] = await resp.json()
            return payload
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_auth.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Type-check**

Run: `uv run mypy custom_components/ica`
Expected: `Success`.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ica/api/auth.py tests/api/test_auth.py
git commit -m "feat(api): add ICA OAuth/DCR/PKCE auth and token refresh"
```

---

### Task 4: API client (`api/client.py`)

Product lookup and **web** shopping-list operations, layered on `IcaAuth`. Handles bearer injection, a single 401 retry (refresh + retry once), and 403 → `IcaGatewayBlockedError`.

> **Phase 1 scope:** only `get_product`, `search_articles`, `get_lists`, `get_list`, `add_item`. `remove_item` (`DELETE .../row/{id}`) and `set_checked` (`PUT .../row/{id}` with the full row) belong to the Phase 2 to-do entity — their endpoints are captured in the appendix, but do NOT implement them here.

**Files:**
- Create: `custom_components/ica/api/client.py`
- Modify: `custom_components/ica/api/__init__.py` (export `IcaClient`)
- Test: `tests/api/test_client.py`

**Interfaces:**
- Consumes: `IcaAuth.async_get_access_token()`, `IcaAuth.token`; `const.SHOPPING_LIST_BASE`, `PRODUCT_URL`, `ARTICLE_SEARCH_URL`, `USER_AGENT`; models (`Product`, `ShoppingList`, `ShoppingListItem`); exceptions.
- Produces `IcaClient(session: aiohttp.ClientSession, auth: IcaAuth)`:
  - `async get_product(ean: str) -> Product | None` — `GET {PRODUCT_URL}/{ean}`; None on 404.
  - `async search_articles(query: str) -> list[dict[str, Any]]` — `GET {ARTICLE_SEARCH_URL}?query=<q>`; returns the raw catalog-article dicts (each carries `articleGroupId`/`expandedArticleGroupId`). Defensively unwraps a bare array or a `{hits|articles|data|result: [...]}` envelope. *(Exact envelope pending the search response capture — see note.)*
  - `async get_lists() -> list[ShoppingList]` — `GET {SHOPPING_LIST_BASE}/list/all` (bare JSON array).
  - `async get_list(list_id: str) -> ShoppingList` — convenience: `get_lists()` filtered by `id`; raises `IcaError` if not found.
  - `async add_item(list_id: str, text: str, article: dict[str, Any] | None = None) -> ShoppingListItem` — `POST {SHOPPING_LIST_BASE}/list/{list_id}/row`, body `{"isStriked": False, "quantity": {}, "text": text, "article"?: article}`; `article` is the raw dict from `search_articles` (or `Product.to_row_article()` as a fallback), passed through verbatim; returns the created row.

- [ ] **Step 1: Write the failing test — `tests/api/test_client.py`**

```python
"""Tests for the ICA API client (mocked HTTP)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses

from custom_components.ica.api import const as c
from custom_components.ica.api.auth import IcaAuth, IcaToken
from custom_components.ica.api.client import IcaClient
from custom_components.ica.api.exceptions import IcaGatewayBlockedError


def _fresh_token() -> IcaToken:
    return IcaToken(
        "access",
        "refresh",
        datetime.now(timezone.utc) + timedelta(hours=1),
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


async def test_search_articles_unwraps_envelope() -> None:
    # Accept either a bare array or a {hits|articles|data|result: [...]} envelope.
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(
                f"{c.ARTICLE_SEARCH_URL}?query=mj%C3%B6lk",
                payload=[{"id": 11103, "name": "mjölk", "articleGroupId": 10}],
            )
            hits = await client.search_articles("mjölk")
    assert hits[0]["articleGroupId"] == 10


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
                "article": {"id": 11103, "group": {"id": 10}, "extendedGroup": {"id": 10}},
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


async def test_gateway_block_raises() -> None:
    async with aiohttp.ClientSession() as session:
        client = _make_client(session)
        with aioresponses() as mock:
            mock.get(f"{c.SHOPPING_LIST_BASE}/list/all", status=403)
            with pytest.raises(IcaGatewayBlockedError):
                await client.get_lists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/api/test_client.py -v`
Expected: FAIL — cannot import `IcaClient`.

- [ ] **Step 3: Create `custom_components/ica/api/client.py`**

```python
"""ICA product, article-search and web shopping-list client (no HA imports)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiohttp

from .auth import IcaAuth
from .const import ARTICLE_SEARCH_URL, PRODUCT_URL, SHOPPING_LIST_BASE, USER_AGENT
from .exceptions import IcaConnectionError, IcaError, IcaGatewayBlockedError
from .models import Product, ShoppingList, ShoppingListItem

# Keys under which the article-search endpoint might nest its hit list. The exact
# envelope is unconfirmed; a bare array is also accepted. Verify at smoke test.
_SEARCH_LIST_KEYS = ("hits", "articles", "data", "result", "results")


class IcaClient:
    """Async client for ICA product lookup, article search and shopping lists."""

    def __init__(self, session: aiohttp.ClientSession, auth: IcaAuth) -> None:
        self._session = session
        self._auth = auth

    async def get_product(self, ean: str) -> Product | None:
        data = await self._request("GET", f"{PRODUCT_URL}/{ean}", allow_404=True)
        if data is None:
            return None
        return Product.from_api(data)

    async def search_articles(self, query: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", ARTICLE_SEARCH_URL, params={"query": query}
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in _SEARCH_LIST_KEYS:
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

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
        params: dict[str, str] | None = None,
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
                method, url, json=json, params=params, headers=headers
            ) as resp:
                if resp.status == 404 and allow_404:
                    return None
                if resp.status == 401 and _retry:
                    token = self._auth.token
                    if token is not None:
                        # Force a refresh, then retry the request exactly once.
                        token.expires_at = datetime.now(timezone.utc)
                    return await self._request(
                        method,
                        url,
                        json=json,
                        params=params,
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
```

- [ ] **Step 4: Add `IcaClient` to `custom_components/ica/api/__init__.py`**

Add to the imports and `__all__`:
```python
from .client import IcaClient
```
and add `"IcaClient",` to `__all__`.

- [ ] **Step 5: Run tests + type-check**

Run: `uv run pytest tests/api/test_client.py -v && uv run mypy custom_components/ica`
Expected: tests PASS; mypy `Success`.

> The add-item tests capture the request body via an `aioresponses` `callback` returning `CallbackResult`. If `search_articles` fails to find hits at smoke test, confirm the real envelope key and add it to `_SEARCH_LIST_KEYS`. The behavioural contract (add posts `{text, isStriked, quantity, article?}` to `/list/{id}/row`) is what matters.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ica/api/client.py custom_components/ica/api/__init__.py tests/api/test_client.py
git commit -m "feat(api): add product lookup and shopping-list operations"
```

---

### Task 5: Integration wiring (`const.py`, `manifest.json`, `__init__.py`, `coordinator.py`)

The HA glue: constants, manifest, config-entry setup/unload with token persistence via `Store`, and the polling coordinator.

**Files:**
- Create: `custom_components/ica/const.py`
- Create: `custom_components/ica/manifest.json`
- Create: `custom_components/ica/coordinator.py`
- Modify: `custom_components/ica/__init__.py` (replace placeholder)
- Test: `tests/conftest.py`, `tests/test_init.py`

**Interfaces:**
- Consumes: `IcaClient`, `IcaAuth`, `IcaToken`, `ShoppingList`, exceptions.
- Produces:
  - `const.py`: `DOMAIN = "ica"`, `CONF_PERSONNUMMER = "personnummer"`, `CONF_PASSWORD = "password"`, `CONF_LIST_ID = "list_id"`, `CONF_LIST_TITLE = "list_title"`, `CONF_TOKEN = "token"`, `CONF_SCAN_INTERVAL = "scan_interval"`, `DEFAULT_SCAN_INTERVAL = 5` (minutes), `UNKNOWN_ITEM_PREFIX = "Okänd vara"`, `PLATFORMS: list = []`.
  - `IcaRuntimeData` dataclass: `client: IcaClient`, `coordinator: IcaDataUpdateCoordinator`.
  - `type IcaConfigEntry = ConfigEntry[IcaRuntimeData]`.
  - `IcaDataUpdateCoordinator(hass, client, list_id, interval)`: `.data` is a `ShoppingList`; raises `ConfigEntryAuthFailed` on `IcaAuthError` (triggers reauth) and creates a repair issue on `IcaGatewayBlockedError`; method `has_item(name: str) -> bool` (case-insensitive over row `text`).
  - `async_setup_entry`, `async_unload_entry`. Token persisted in **entry data** via `async_update_entry` (no separate `Store`, avoiding a dual-source staleness bug); refreshed tokens do NOT trigger a reload because the update listener only re-applies the poll interval.

- [ ] **Step 1: Create `custom_components/ica/const.py`**

```python
"""Constants for the ICA integration."""

from __future__ import annotations

DOMAIN = "ica"

CONF_PERSONNUMMER = "personnummer"
CONF_PASSWORD = "password"
CONF_LIST_ID = "list_id"
CONF_LIST_TITLE = "list_title"
CONF_TOKEN = "token"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 5  # minutes

UNKNOWN_ITEM_PREFIX = "Okänd vara"

PLATFORMS: list[str] = []  # Phase 2 adds "todo"
```

- [ ] **Step 2: Create `custom_components/ica/manifest.json`**

```json
{
  "domain": "ica",
  "name": "ICA Shopping List",
  "codeowners": ["@davidhaglund"],
  "config_flow": true,
  "dependencies": [],
  "documentation": "https://github.com/davidhaglund/barcode-ica-shopping-list",
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/davidhaglund/barcode-ica-shopping-list/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

- [ ] **Step 3: Create `custom_components/ica/coordinator.py`**

```python
"""Data update coordinator for the ICA shopping list."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IcaClient, IcaError, ShoppingList
from .api.exceptions import IcaAuthError, IcaGatewayBlockedError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ISSUE_GATEWAY_BLOCKED = "gateway_blocked"


class IcaDataUpdateCoordinator(DataUpdateCoordinator[ShoppingList]):
    """Polls a single ICA shopping list."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: IcaClient,
        list_id: str,
        interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="ICA shopping list",
            update_interval=timedelta(minutes=interval_minutes),
        )
        self.client = client
        self.list_id = list_id

    async def _async_update_data(self) -> ShoppingList:
        try:
            data = await self.client.get_list(self.list_id)
        except IcaGatewayBlockedError as err:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_GATEWAY_BLOCKED,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_GATEWAY_BLOCKED,
            )
            raise UpdateFailed(str(err)) from err
        except IcaAuthError as err:
            # Surfaces the HA reauth flow (spec: hard 401 -> reauth).
            raise ConfigEntryAuthFailed(str(err)) from err
        except IcaError as err:
            raise UpdateFailed(str(err)) from err
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_GATEWAY_BLOCKED)
        return data

    def has_item(self, name: str) -> bool:
        """Return True if an item with this name (case-insensitive) exists."""
        if self.data is None:
            return False
        target = name.strip().casefold()
        return any(
            item.text.strip().casefold() == target for item in self.data.items
        )
```

- [ ] **Step 4: Replace `custom_components/ica/__init__.py`**

```python
"""ICA Shopping List integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import IcaClient
from .api.auth import IcaAuth, IcaToken
from .const import (
    CONF_LIST_ID,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import IcaDataUpdateCoordinator
from .services import async_setup_services, async_unload_services


@dataclass
class IcaRuntimeData:
    """Runtime objects stored on the config entry."""

    client: IcaClient
    coordinator: IcaDataUpdateCoordinator


type IcaConfigEntry = ConfigEntry[IcaRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: IcaConfigEntry) -> bool:
    """Set up ICA from a config entry."""
    session = async_get_clientsession(hass)
    token = IcaToken.from_dict(entry.data[CONF_TOKEN])

    async def _save_token(new_token: IcaToken) -> None:
        # Persist refreshed tokens back to the config entry (single source of
        # truth). The update listener below only re-applies the poll interval,
        # so this does NOT trigger a reload loop.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: new_token.to_dict()}
        )

    auth = IcaAuth(session, token=token, token_updated=_save_token)
    client = IcaClient(session, auth)

    interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = IcaDataUpdateCoordinator(
        hass, client, entry.data[CONF_LIST_ID], interval
    )
    # first_refresh raises ConfigEntryNotReady / ConfigEntryAuthFailed itself
    # based on what the coordinator raised (UpdateFailed / ConfigEntryAuthFailed).
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = IcaRuntimeData(client=client, coordinator=coordinator)

    await async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IcaConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        async_unload_services(hass)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: IcaConfigEntry) -> None:
    """Apply changed options (poll interval) live, without a full reload.

    This runs on every entry update, including token refreshes — it must stay
    idempotent and side-effect-free beyond re-setting the interval.
    """
    entry.runtime_data.coordinator.update_interval = timedelta(
        minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
```

- [ ] **Step 5: Create `tests/conftest.py`**

```python
"""Shared fixtures for HA-aware tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading custom_components in every test."""
    return None
```

- [ ] **Step 6: Write the failing test — `tests/test_init.py`**

```python
"""Tests for config-entry setup/unload and coordinator dedupe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.models import ShoppingList, ShoppingListItem
from custom_components.ica.const import CONF_LIST_ID, CONF_TOKEN, DOMAIN


def _entry() -> MockConfigEntry:
    token = IcaToken(
        "a", "r", datetime.now(timezone.utc) + timedelta(hours=1), "c", "s", "sc"
    )
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOKEN: token.to_dict(), CONF_LIST_ID: "G1", "list_title": "Inköpslista"},
        entry_id="entry1",
    )


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    lst = ShoppingList(
        id="G1",
        name="Inköpslista",
        items=[ShoppingListItem("R1", "Mjölk", False)],
    )
    with patch(
        "custom_components.ica.IcaClient.get_list", AsyncMock(return_value=lst)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data.coordinator
    assert coordinator.has_item("mjölk") is True
    assert coordinator.has_item("saknas") is False

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `uv run pytest tests/test_init.py -v`
Expected: FAIL — `services` module not found (created in Task 7) / import error.

> This task depends on `services.py` existing for the import. Create a minimal stub now so setup works, then flesh it out in Task 7:

- [ ] **Step 8: Create a temporary `custom_components/ica/services.py` stub**

```python
"""ICA services (stub; implemented in Task 7)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register ICA services (stub)."""


def async_unload_services(hass: HomeAssistant) -> None:
    """Unregister ICA services (stub)."""
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `uv run pytest tests/test_init.py -v && uv run mypy custom_components/ica`
Expected: test PASS; mypy `Success`.

- [ ] **Step 10: Commit**

```bash
git add custom_components/ica/const.py custom_components/ica/manifest.json \
  custom_components/ica/coordinator.py custom_components/ica/__init__.py \
  custom_components/ica/services.py tests/conftest.py tests/test_init.py
git commit -m "feat: add config-entry setup, token storage, and coordinator"
```

---

### Task 6: Config flow (setup + reauth + options)

Credentials → authenticate → pick default list. Reauth on 401. Options for the poll interval.

**Files:**
- Create: `custom_components/ica/config_flow.py`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `IcaAuth.login`, `IcaClient.get_lists`, models, exceptions; const keys.
- Produces: `IcaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN)` with steps `async_step_user`, `async_step_pick_list`, `async_step_reauth`, `async_step_reauth_confirm`; `IcaOptionsFlow` with `async_step_init`.

- [ ] **Step 1: Write the failing test — `tests/test_config_flow.py`**

```python
"""Tests for the ICA config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.models import ShoppingList
from custom_components.ica.const import (
    CONF_LIST_ID,
    CONF_PASSWORD,
    CONF_PERSONNUMMER,
    DOMAIN,
)


def _token() -> IcaToken:
    from datetime import datetime, timedelta, timezone

    return IcaToken(
        "a", "r", datetime.now(timezone.utc) + timedelta(hours=1), "c", "s", "sc"
    )


async def test_full_user_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    lists = [ShoppingList(id="G1", name="Inköpslista")]
    with (
        patch(
            "custom_components.ica.config_flow.IcaAuth.login",
            AsyncMock(return_value=_token()),
        ),
        patch(
            "custom_components.ica.config_flow.IcaClient.get_lists",
            AsyncMock(return_value=lists),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PERSONNUMMER: "199001010000", CONF_PASSWORD: "secret"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "pick_list"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LIST_ID: "G1"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LIST_ID] == "G1"


async def test_invalid_auth_shows_error(hass: HomeAssistant) -> None:
    from custom_components.ica.api.exceptions import IcaAuthError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.ica.config_flow.IcaAuth.login",
        AsyncMock(side_effect=IcaAuthError("bad")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PERSONNUMMER: "199001010000", CONF_PASSWORD: "wrong"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_config_flow.py -v`
Expected: FAIL — no `config_flow` module.

- [ ] **Step 3: Create `custom_components/ica/config_flow.py`**

```python
"""Config flow for the ICA integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import IcaClient, IcaConnectionError
from .api.auth import IcaAuth, IcaToken
from .api.exceptions import IcaAuthError
from .const import (
    CONF_LIST_ID,
    CONF_LIST_TITLE,
    CONF_PASSWORD,
    CONF_PERSONNUMMER,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PERSONNUMMER): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class IcaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the ICA config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._token: IcaToken | None = None
        self._lists: dict[str, str] = {}  # list id (GUID) -> list name

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            auth = IcaAuth(session)
            try:
                self._token = await auth.login(
                    user_input[CONF_PERSONNUMMER], user_input[CONF_PASSWORD]
                )
                client = IcaClient(session, auth)
                lists = await client.get_lists()
            except IcaAuthError:
                errors["base"] = "invalid_auth"
            except IcaConnectionError:
                errors["base"] = "cannot_connect"
            else:
                self._lists = {x.id: x.name for x in lists}
                return await self.async_step_pick_list()
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_pick_list(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            assert self._token is not None
            list_id = user_input[CONF_LIST_ID]
            await self.async_set_unique_id(list_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"ICA – {self._lists[list_id]}",
                data={
                    CONF_TOKEN: self._token.to_dict(),
                    CONF_LIST_ID: list_id,
                    CONF_LIST_TITLE: self._lists[list_id],
                },
            )
        schema = vol.Schema(
            {vol.Required(CONF_LIST_ID): vol.In(self._lists)}
        )
        return self.async_show_form(step_id="pick_list", data_schema=schema)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            auth = IcaAuth(session)
            try:
                token = await auth.login(
                    user_input[CONF_PERSONNUMMER], user_input[CONF_PASSWORD]
                )
            except IcaAuthError:
                errors["base"] = "invalid_auth"
            except IcaConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: token.to_dict()}
                )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> "IcaOptionsFlow":
        return IcaOptionsFlow()


class IcaOptionsFlow(OptionsFlow):
    """Options: poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    cv.positive_int, vol.Range(min=1, max=1440)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config_flow.py -v && uv run mypy custom_components/ica`
Expected: both tests PASS; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ica/config_flow.py tests/test_config_flow.py
git commit -m "feat: add config flow with reauth and options"
```

---

### Task 7: Services (`services.py`, `services.yaml`)

Replace the Task 5 stub with the three real services, all returning structured response data.

**Files:**
- Modify: `custom_components/ica/services.py` (replace stub)
- Create: `custom_components/ica/services.yaml`
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: `IcaConfigEntry.runtime_data` (`client`, `coordinator`), `IcaClient`, `ShoppingList`, `UNKNOWN_ITEM_PREFIX`, exceptions.
- Produces registered services `ica.lookup_product`, `ica.add_item`, `ica.scan_barcode`.
  - `lookup_product(barcode)` → `{found, name, ean}`.
  - `add_item(name, list?)` → `{added, name}`.
  - `scan_barcode(barcode, list?)` → `{found, added, name, ean}`.

- [ ] **Step 1: Write the failing test — `tests/test_services.py`**

```python
"""Tests for ICA services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.models import Product, ShoppingList, ShoppingListItem
from custom_components.ica.const import CONF_LIST_ID, CONF_LIST_TITLE, CONF_TOKEN, DOMAIN


def _token_dict() -> dict[str, str]:
    return IcaToken(
        "a", "r", datetime.now(timezone.utc) + timedelta(hours=1), "c", "s", "sc"
    ).to_dict()


async def _setup(hass: HomeAssistant, items: list[ShoppingListItem]) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOKEN: _token_dict(), CONF_LIST_ID: "G1", CONF_LIST_TITLE: "Inköpslista"},
        entry_id="e1",
    )
    entry.add_to_hass(hass)
    lst = ShoppingList(id="G1", name="Inköpslista", items=items)
    with patch(
        "custom_components.ica.IcaClient.get_list", AsyncMock(return_value=lst)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_lookup_product_found(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with patch(
        "custom_components.ica.services.IcaClient.get_product",
        AsyncMock(return_value=Product("Mjölk", "7311041000000", 1, 10, 10)),
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "lookup_product",
            {"barcode": "7311041000000"},
            blocking=True,
            return_response=True,
        )
    assert resp == {"found": True, "name": "Mjölk", "ean": "7311041000000"}


async def test_scan_barcode_attaches_article(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with (
        patch(
            "custom_components.ica.services.IcaClient.get_product",
            AsyncMock(return_value=Product("mjölk", "7310865000293", 11103, 10, 10)),
        ),
        patch(
            "custom_components.ica.services.IcaClient.search_articles",
            AsyncMock(return_value=[{"name": "mjölk", "id": 11103, "articleGroupId": 10}]),
        ),
        patch("custom_components.ica.services.IcaClient.add_item", AsyncMock()) as add,
        patch(
            "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh",
            AsyncMock(),
        ),
    ):
        resp = await hass.services.async_call(
            DOMAIN, "scan_barcode", {"barcode": "7310865000293"},
            blocking=True, return_response=True,
        )
    # The matching search hit (with its articleGroupId) is attached to the add.
    _, kwargs = add.await_args
    assert kwargs["article"]["articleGroupId"] == 10
    assert resp == {"found": True, "added": True, "name": "mjölk", "ean": "7310865000293"}


async def test_scan_barcode_miss_adds_raw_ean(hass: HomeAssistant) -> None:
    await _setup(hass, [])
    with (
        patch(
            "custom_components.ica.services.IcaClient.get_product",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.ica.services.IcaClient.add_item", AsyncMock()
        ) as add,
        patch(
            "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh",
            AsyncMock(),
        ),
    ):
        resp = await hass.services.async_call(
            DOMAIN,
            "scan_barcode",
            {"barcode": "999"},
            blocking=True,
            return_response=True,
        )
    add.assert_awaited_once_with("G1", "Okänd vara 999", article=None)
    assert resp == {"found": False, "added": True, "name": "Okänd vara 999", "ean": "999"}


async def test_add_item_dedupes(hass: HomeAssistant) -> None:
    await _setup(hass, [ShoppingListItem("R1", "Mjölk", False)])
    with (
        patch("custom_components.ica.services.IcaClient.add_item", AsyncMock()) as add,
        patch(
            "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh",
            AsyncMock(),
        ),
    ):
        resp = await hass.services.async_call(
            DOMAIN, "add_item", {"name": "mjölk"}, blocking=True, return_response=True
        )
    add.assert_not_awaited()
    assert resp == {"added": False, "name": "mjölk"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_services.py -v`
Expected: FAIL — services not registered / stub returns nothing.

- [ ] **Step 3: Replace `custom_components/ica/services.py`**

```python
"""ICA services: lookup_product, add_item, scan_barcode."""

from __future__ import annotations

from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .api import IcaClient, IcaError, Product
from .const import DOMAIN, UNKNOWN_ITEM_PREFIX

SERVICE_LOOKUP_PRODUCT = "lookup_product"
SERVICE_ADD_ITEM = "add_item"
SERVICE_SCAN_BARCODE = "scan_barcode"

ATTR_BARCODE = "barcode"
ATTR_NAME = "name"
ATTR_LIST = "list"

_LOOKUP_SCHEMA = vol.Schema({vol.Required(ATTR_BARCODE): cv.string})
_ADD_SCHEMA = vol.Schema(
    {vol.Required(ATTR_NAME): cv.string, vol.Optional(ATTR_LIST): cv.string}
)
_SCAN_SCHEMA = vol.Schema(
    {vol.Required(ATTR_BARCODE): cv.string, vol.Optional(ATTR_LIST): cv.string}
)


def _get_runtime(hass: HomeAssistant) -> Any:
    """Return the runtime data of the single loaded ICA config entry."""
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise HomeAssistantError("ICA integration is not set up")
    return entries[0].runtime_data


async def _resolve_list_id(runtime: Any, list_name: str | None) -> str:
    """Return the id (GUID) of the target list (default if not named)."""
    if list_name is None:
        return cast(str, runtime.coordinator.list_id)
    client: IcaClient = runtime.client
    for lst in await client.get_lists():
        if lst.name.strip().casefold() == list_name.strip().casefold():
            return lst.id
    raise ServiceValidationError(f"No ICA list named '{list_name}'")


async def _resolve_article(client: IcaClient, product: Product) -> dict[str, Any] | None:
    """Find the best catalog article for a product, for correct categorisation.

    Prefers an exact-name search hit, else the first hit, else a minimal article
    built from the product's own group ids; None if we have nothing to attach.
    """
    try:
        hits = await client.search_articles(product.name)
    except IcaError:
        hits = []
    target = product.name.strip().casefold()
    for hit in hits:
        if str(hit.get("name", "")).strip().casefold() == target:
            return hit
    if hits:
        return hits[0]
    if product.article_group_id is not None:
        return product.to_row_article()
    return None


async def _add_deduped(
    runtime: Any, list_id: str, name: str, article: dict[str, Any] | None = None
) -> bool:
    """Add an item unless a case-insensitive name match already exists.

    Returns True if it was added, False if it was a duplicate.
    """
    coordinator = runtime.coordinator
    is_default = list_id == coordinator.list_id
    if is_default and coordinator.has_item(name):
        return False
    if not is_default:
        existing = await runtime.client.get_list(list_id)
        target = name.strip().casefold()
        if any(i.text.strip().casefold() == target for i in existing.items):
            return False
    await runtime.client.add_item(list_id, name, article=article)
    if is_default:
        await coordinator.async_request_refresh()
    return True


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register ICA services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_LOOKUP_PRODUCT):
        return

    async def lookup_product(call: ServiceCall) -> ServiceResponse:
        runtime = _get_runtime(hass)
        client: IcaClient = runtime.client
        try:
            product = await client.get_product(call.data[ATTR_BARCODE])
        except IcaError as err:
            raise HomeAssistantError(str(err)) from err
        if product is None:
            return {"found": False, "name": None, "ean": call.data[ATTR_BARCODE]}
        return {"found": True, "name": product.name, "ean": product.ean}

    async def add_item(call: ServiceCall) -> ServiceResponse:
        runtime = _get_runtime(hass)
        name = call.data[ATTR_NAME]
        try:
            list_id = await _resolve_list_id(runtime, call.data.get(ATTR_LIST))
            added = await _add_deduped(runtime, list_id, name)
        except IcaError as err:
            raise HomeAssistantError(str(err)) from err
        return {"added": added, "name": name}

    async def scan_barcode(call: ServiceCall) -> ServiceResponse:
        runtime = _get_runtime(hass)
        client: IcaClient = runtime.client
        ean = call.data[ATTR_BARCODE]
        try:
            product = await client.get_product(ean)
            list_id = await _resolve_list_id(runtime, call.data.get(ATTR_LIST))
            if product is not None:
                name = product.name
                found = True
                # Attach the catalog article so ICA files it in the right category.
                article = await _resolve_article(client, product)
            else:
                name = f"{UNKNOWN_ITEM_PREFIX} {ean}"
                found = False
                article = None
            added = await _add_deduped(runtime, list_id, name, article=article)
        except IcaError as err:
            raise HomeAssistantError(str(err)) from err
        return {"found": found, "added": added, "name": name, "ean": ean}

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOOKUP_PRODUCT,
        lookup_product,
        schema=_LOOKUP_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_ITEM,
        add_item,
        schema=_ADD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_BARCODE,
        scan_barcode,
        schema=_SCAN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Unregister ICA services."""
    for name in (SERVICE_LOOKUP_PRODUCT, SERVICE_ADD_ITEM, SERVICE_SCAN_BARCODE):
        hass.services.async_remove(DOMAIN, name)
```

- [ ] **Step 4: Create `custom_components/ica/services.yaml`**

```yaml
lookup_product:
  fields:
    barcode:
      required: true
      example: "7311041000000"
      selector:
        text:

add_item:
  fields:
    name:
      required: true
      example: "Mjölk"
      selector:
        text:
    list:
      required: false
      example: "Inköpslista"
      selector:
        text:

scan_barcode:
  fields:
    barcode:
      required: true
      example: "7311041000000"
      selector:
        text:
    list:
      required: false
      example: "Inköpslista"
      selector:
        text:
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_services.py -v && uv run mypy custom_components/ica`
Expected: all 4 tests PASS; mypy `Success`.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ica/services.py custom_components/ica/services.yaml tests/test_services.py
git commit -m "feat: add lookup_product, add_item, and scan_barcode services"
```

---

### Task 8: Translations, validation, and manual smoke test

Add bilingual UI strings, make the whole suite green, and validate against a real ICA account.

**Files:**
- Create: `custom_components/ica/strings.json`
- Create: `custom_components/ica/translations/en.json`
- Create: `custom_components/ica/translations/sv.json`

**Interfaces:**
- Consumes: config-flow step ids (`user`, `pick_list`, `reauth_confirm`), error keys (`invalid_auth`, `cannot_connect`), abort key (`reauth_successful`), option key (`scan_interval`), the repair-issue key (`gateway_blocked`), service names/fields.
- Produces: HA-loadable translations validated by `hassfest`.

- [ ] **Step 1: Create `custom_components/ica/strings.json`**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "ICA account",
        "description": "Sign in with your ICA personnummer and password.",
        "data": {
          "personnummer": "Personnummer (12 digits)",
          "password": "Password"
        }
      },
      "pick_list": {
        "title": "Default shopping list",
        "data": {
          "list_id": "Shopping list"
        }
      },
      "reauth_confirm": {
        "title": "Re-authenticate ICA",
        "description": "Your ICA session expired. Enter your password again.",
        "data": {
          "personnummer": "Personnummer (12 digits)",
          "password": "Password"
        }
      }
    },
    "error": {
      "invalid_auth": "Invalid personnummer or password.",
      "cannot_connect": "Could not reach ICA. Check your connection (a Swedish IP is required)."
    },
    "abort": {
      "already_configured": "This shopping list is already configured.",
      "reauth_successful": "Re-authentication was successful."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "ICA options",
        "data": {
          "scan_interval": "Sync interval (minutes)"
        }
      }
    }
  },
  "issues": {
    "gateway_blocked": {
      "title": "ICA is blocking requests",
      "description": "ICA's API rejected requests, usually because Home Assistant is not connecting from a Swedish IP address. ICA only accepts connections from Sweden."
    }
  },
  "services": {
    "lookup_product": {
      "name": "Look up product",
      "description": "Look up a product by barcode (EAN/GTIN) without changing any list.",
      "fields": {
        "barcode": {
          "name": "Barcode",
          "description": "The scanned EAN/GTIN."
        }
      }
    },
    "add_item": {
      "name": "Add item",
      "description": "Add an item to a shopping list (skipped if already present).",
      "fields": {
        "name": {
          "name": "Name",
          "description": "The item text (in Swedish)."
        },
        "list": {
          "name": "List",
          "description": "Target list title. Defaults to the configured list."
        }
      }
    },
    "scan_barcode": {
      "name": "Scan barcode",
      "description": "Look up a barcode and add the product to a shopping list. Unknown barcodes are added as 'Okänd vara <ean>'.",
      "fields": {
        "barcode": {
          "name": "Barcode",
          "description": "The scanned EAN/GTIN."
        },
        "list": {
          "name": "List",
          "description": "Target list title. Defaults to the configured list."
        }
      }
    }
  }
}
```

- [ ] **Step 2: Create `custom_components/ica/translations/en.json`** (identical to `strings.json`)

Copy the exact contents of `strings.json` into `translations/en.json`.

- [ ] **Step 3: Create `custom_components/ica/translations/sv.json`**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "ICA-konto",
        "description": "Logga in med ditt ICA-personnummer och lösenord.",
        "data": {
          "personnummer": "Personnummer (12 siffror)",
          "password": "Lösenord"
        }
      },
      "pick_list": {
        "title": "Standardinköpslista",
        "data": {
          "list_id": "Inköpslista"
        }
      },
      "reauth_confirm": {
        "title": "Autentisera ICA igen",
        "description": "Din ICA-session har gått ut. Ange ditt lösenord igen.",
        "data": {
          "personnummer": "Personnummer (12 siffror)",
          "password": "Lösenord"
        }
      }
    },
    "error": {
      "invalid_auth": "Felaktigt personnummer eller lösenord.",
      "cannot_connect": "Kunde inte nå ICA. Kontrollera anslutningen (svensk IP krävs)."
    },
    "abort": {
      "already_configured": "Den här inköpslistan är redan konfigurerad.",
      "reauth_successful": "Återautentiseringen lyckades."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "ICA-inställningar",
        "data": {
          "scan_interval": "Synkroniseringsintervall (minuter)"
        }
      }
    }
  },
  "issues": {
    "gateway_blocked": {
      "title": "ICA blockerar anrop",
      "description": "ICA:s API avvisade anropen, oftast för att Home Assistant inte ansluter från en svensk IP-adress. ICA tillåter endast anslutningar från Sverige."
    }
  },
  "services": {
    "lookup_product": {
      "name": "Slå upp produkt",
      "description": "Slå upp en produkt via streckkod (EAN/GTIN) utan att ändra någon lista.",
      "fields": {
        "barcode": {
          "name": "Streckkod",
          "description": "Den skannade EAN/GTIN-koden."
        }
      }
    },
    "add_item": {
      "name": "Lägg till vara",
      "description": "Lägg till en vara i en inköpslista (hoppas över om den redan finns).",
      "fields": {
        "name": {
          "name": "Namn",
          "description": "Varans text."
        },
        "list": {
          "name": "Lista",
          "description": "Mållistans titel. Standard är den konfigurerade listan."
        }
      }
    },
    "scan_barcode": {
      "name": "Skanna streckkod",
      "description": "Slå upp en streckkod och lägg till produkten i en inköpslista. Okända streckkoder läggs till som 'Okänd vara <ean>'.",
      "fields": {
        "barcode": {
          "name": "Streckkod",
          "description": "Den skannade EAN/GTIN-koden."
        },
        "list": {
          "name": "Lista",
          "description": "Mållistans titel. Standard är den konfigurerade listan."
        }
      }
    }
  }
}
```

- [ ] **Step 4: Run the full suite and all gates**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/ica
uv run pytest
```
Expected: ruff clean; mypy `Success`; all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ica/strings.json custom_components/ica/translations
git commit -m "feat: add English and Swedish UI translations"
```

- [ ] **Step 6: Manual smoke test (definitive validation — requires Swedish IP + real ICA account)**

This is the acceptance gate the mocked tests cannot cover.

1. Copy `custom_components/ica/` into a Home Assistant `config/custom_components/` (or add the repo via HACS as a custom repository) and restart HA.
2. Settings → Devices & Services → Add Integration → "ICA Shopping List". Enter your 12-digit personnummer + password. Confirm the list picker shows your real lists; pick your default.
3. Developer Tools → Actions → `ica.lookup_product` with a real grocery EAN → confirm `found: true` and the correct name. If the name is wrong/missing, capture the raw response and reconcile `Product.from_api` (Task 2) with the real JSON.
4. Call `ica.scan_barcode` with the same EAN → confirm the item appears in the ICA app **in the correct category/aisle** (e.g. a dairy EAN lands under Mejeri). Call it again → confirm it is NOT duplicated (dedupe). If categorisation is wrong, inspect the `search?query=<name>` response and confirm `_SEARCH_LIST_KEYS` / the attached `article` shape.
5. Call `ica.scan_barcode` with a nonsense number (e.g. `0000000000000`) → confirm `found: false` and an `Okänd vara 0000000000000` item is added (uncategorised is fine).
6. Wait for/trigger a coordinator refresh → confirm no auth errors after ~15 min (token refresh path).

- [ ] **Step 7: Record smoke-test results** in the PR / commit message, noting any corrections to `Product.from_api`, the article-search envelope, or the add-row `article` shape.

---

## Notes for the executor

- **Auth is reverse-engineered.** If a login step fails during the smoke test, diff your request against `ica_mcp/client.py` (cited in Task 3) — the likely culprits are redirect handling (`allow_redirects=False`) or the SSO-token HTML regex.
- **The shopping-list API is the ICA.se *web* API** (`.../digx/shopping-list/v1/...`), confirmed against the user's real traffic — see the appendix for exact requests/responses. It is NOT ica-mcp's mobile shopping-list service; only auth + product lookup come from ica-mcp.
- **Article search envelope is unconfirmed.** `search_articles` accepts a bare array or a `{hits|articles|data|result|results}` envelope. If the smoke test finds no hits, capture the real `search?query=` body and adjust `_SEARCH_LIST_KEYS`.
- **Do not** add runtime dependencies to `manifest.json`; if you think you need one, you probably don't (stdlib + `aiohttp` cover it).
- **`brand` was intentionally dropped** from the `lookup_product` response the spec sketched (`{found, name, ean, brand?}`). Upstream `ica-mcp` reads only `gtin`/`name`/`articleId`/`articleGroupId` from the product response — there is no reliable brand field — so the response is `{found, name, ean}`. If a real product response (smoke test) exposes a brand field, add it to `Product.from_api` and the service response then.

---

## Appendix: confirmed ICA web API (captured from real traffic)

All on `https://apimgw-pub.ica.se`, Bearer-token auth (the DCR/PKCE flow in Task 3).
Base `SHOPPING_LIST_BASE = .../sverige/digx/shopping-list/v1/api`.

### Read all lists (Phase 1) — `GET {SHOPPING_LIST_BASE}/list/all`
Returns a **bare JSON array** of lists. Each list:
```jsonc
{ "id": "<GUID>", "name": "Att handla", "comment": "", "sortingStore": 8900,
  "rows": [ /* rows, see below */ ],
  "shoppingListId": 36891048, "householdId": 538959503, "secureId": "<GUID>" }
```
Each row:
```jsonc
{ "id": "<row GUID>", "text": "mjölk", "isStriked": false, "order": -184,
  "quantity": null | { "amount": 2.0, "unit": "st" },
  "article": { "id": 11103, "name": null, "ean": null,
               "group": { "id": 10, "name": null },
               "extendedGroup": { "id": 10, "name": null } },
  "shoppingListRowId": 1030857476, "ingredientGroup": 0 }
```
Observed `group.id` semantics: 4 = Frukt & Grönt, 5 = Fryst, 6 = Ost, 10 = Mejeri,
9 = Skafferi/Övrigt (catch-all; `extendedGroup` splits it), 11 = Hushåll, 3/12 = Godis.
Names come back `null` (resolve via a separate reference endpoint if ever needed).

### Article search (Phase 1) — `GET .../sverige/digx/shoppinglistarticlesearch/v1/search?query=<q>`
Autocomplete the web app runs before adding. Returns catalog articles carrying
`id`, `name`, `productEan`, `articleGroupId`, `expandedArticleGroupId`,
`articleGroupName`, `expandedArticleGroupName` (+ `_id` like `"shoppingarticle_11103"`).
**Response envelope not yet captured** — `search_articles` handles array or
`{hits|articles|data|result|results}`.

### Add a row (Phase 1) — `POST {SHOPPING_LIST_BASE}/list/{listId}/row`
Request (the `article` object is a search hit, passed through verbatim):
```jsonc
{ "isStriked": false, "quantity": {}, "text": "mjölk",
  "article": { "_id": "shoppingarticle_11103", "id": 11103, "name": "mjölk",
               "productEan": "7310865000293",
               "articleGroupId": 10, "expandedArticleGroupId": 10,
               "articleGroupName": "Mejeri", "expandedArticleGroupName": "Mejeri", ... } }
```
Free-text add (no match) omits `article`; ICA assigns a negative `article.id` and a
default group server-side. Response = the created row (row shape above).

### Update / check a row (Phase 2) — `PUT {SHOPPING_LIST_BASE}/row/{rowId}`
Body = the **full row** object with `isStriked` toggled (note: keyed on the row
GUID under `/row/`, not `/list/{id}/`). Response = updated row.

### Delete a row (Phase 2) — `DELETE {SHOPPING_LIST_BASE}/row/{rowId}`
No request body.

### Product lookup by EAN (Phase 1) — `GET {PRODUCT_URL}/{ean}`
`PRODUCT_URL = .../sverige/digx/mobile/productservice/v1/product`. From `ica-mcp`;
returns `gtin`, `name`, `articleId`, `articleGroupId`, `expandedArticleGroupId`
(200) or 404 when unknown. **Exact shape to be confirmed at smoke test.**
