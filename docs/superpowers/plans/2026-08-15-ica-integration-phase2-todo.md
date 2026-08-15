# ICA Integration — Phase 2 (To-do List Entity) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the configured ICA shopping list in Home Assistant as a native `TodoListEntity` — add, delete, check off and rename items from the To-do card and by voice (Assist).

**Architecture:** `ShoppingListItem` starts preserving its full raw row so ICA's replace-the-whole-row update endpoint can be used without destroying fields we don't model. The HA-free client gains `update_item`/`remove_item`. The service layer's ICA→HA error mapping moves to a shared module so the new entity inherits it unchanged. A single `IcaTodoListEntity` (a `CoordinatorEntity`) then maps rows ⇄ `TodoItem`s.

**Tech Stack:** Python 3.13, Home Assistant 2025.4.4, `aiohttp`, `uv`, `ruff`, `mypy` (strict), `pytest` + `pytest-homeassistant-custom-component`.

## Global Constraints

- Integration domain is exactly `ica`. `manifest.json` `requirements` stays `[]` (no new runtime deps).
- **`custom_components/ica/api/` MUST NOT import from `homeassistant`** — it stays pure Python (`aiohttp` + stdlib only).
- **Full-row preservation is the point of this plan.** ICA's `PUT .../row/{id}` replaces the entire row. Any update must send back every field we received (`article`, `order`, `quantity`, `created`, `createdBy`, `shoppingListRowId`, `ingredientGroup`, …) with only the intended fields changed. Dropping `article` would destroy the item's category.
- **UI/voice adds are NOT deduped** — they always add. (The scanner services keep their merge-no-count dedupe; do not touch `services.py` dedupe behavior.)
- **MOVE_TODO_ITEM is out of scope** — no reordering, no `order` management.
- All code fully type-annotated. Every task ends with `uv run ruff check .` clean, `uv run ruff format custom_components tests` applied, `uv run mypy custom_components/ica` Success, and `uv run pytest` all green. No `# noqa`.
- The env is already synced — you do not need `uv sync` (nothing here adds a dependency). Use `uv run …`.
- **Committing from a sandbox needs the git config bypass** (repo-local `[user]` is already configured):
  `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git add … && GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git commit -m "…"`
- Confirmed endpoints (captured from the live account — do not invent others):
  - update/check/rename a row: `PUT {SHOPPING_LIST_BASE}/row/{row_id}`, body = the full row
  - delete a row: `DELETE {SHOPPING_LIST_BASE}/row/{row_id}`, no body

---

### Task 1: Preserve the full row on `ShoppingListItem`

**Files:**
- Modify: `custom_components/ica/api/models.py` (class `ShoppingListItem`)
- Test: `tests/api/test_models.py`

**Interfaces:**
- Consumes: the existing `_required()` helper in `models.py`.
- Produces:
  - `ShoppingListItem.raw: dict[str, Any]` (defaults to `{}`), populated by `from_api`.
  - `ShoppingListItem.to_updated_row(*, text: str | None = None, is_checked: bool | None = None) -> dict[str, Any]` — the full row with only the given fields replaced.

- [ ] **Step 1: Write the failing tests** (append to `tests/api/test_models.py`)

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_models.py -q -k "raw_row or to_updated_row"`
Expected: FAIL — `AttributeError: 'ShoppingListItem' object has no attribute 'raw'` / `... has no attribute 'to_updated_row'`.

- [ ] **Step 3: Implement**

In `custom_components/ica/api/models.py`, replace the `ShoppingListItem` class body with:

```python
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
        """
        row = dict(self.raw)
        row.setdefault("id", self.id)
        row["text"] = self.text if text is None else text
        row["isStriked"] = self.is_checked if is_checked is None else is_checked
        return row
```

(`field` is already imported in this module; `Any` too.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_models.py -v`
Expected: all PASS (the pre-existing model tests included).

- [ ] **Step 5: Run the full gates**

Run: `uv run pytest -q && uv run mypy custom_components/ica && uv run ruff check .`
Expected: all green. (Existing tests construct `ShoppingListItem("R1", "Mjölk", False)` positionally — `raw` defaults, so they keep working.)

- [ ] **Step 6: Commit**

```bash
GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git add custom_components/ica/api/models.py tests/api/test_models.py
GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git commit -m "feat(api): keep the full row on ShoppingListItem for round-trip updates"
```

---

### Task 2: Client row update + delete

**Files:**
- Modify: `custom_components/ica/api/client.py`
- Test: `tests/api/test_client.py`

**Interfaces:**
- Consumes: `ShoppingListItem.to_updated_row()` (Task 1); the existing `_request()`, `SHOPPING_LIST_BASE`, `IcaError`.
- Produces:
  - `IcaClient.update_item(item: ShoppingListItem, *, text: str | None = None, is_checked: bool | None = None) -> ShoppingListItem`
  - `IcaClient.remove_item(item_id: str) -> None`

- [ ] **Step 1: Write the failing tests** (append to `tests/api/test_client.py`)

```python
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
```

Add `ShoppingListItem` to this test module's imports from `custom_components.ica.api.models` if it is not already imported.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_client.py -q -k "update_item or remove_item"`
Expected: FAIL — `AttributeError: 'IcaClient' object has no attribute 'update_item'`.

- [ ] **Step 3: Implement** — add to `IcaClient` in `custom_components/ica/api/client.py`, directly after `add_item`

```python
    async def update_item(
        self,
        item: ShoppingListItem,
        *,
        text: str | None = None,
        is_checked: bool | None = None,
    ) -> ShoppingListItem:
        """Update a row's text and/or checked state.

        ICA REPLACES the row, so the complete payload is sent back with only
        the requested fields changed — see `ShoppingListItem.to_updated_row`.
        """
        body = item.to_updated_row(text=text, is_checked=is_checked)
        data = await self._request(
            "PUT", f"{SHOPPING_LIST_BASE}/row/{item.id}", json=body
        )
        if data is None:
            raise IcaError(f"ICA API returned no data updating row {item.id}")
        return ShoppingListItem.from_api(data)

    async def remove_item(self, item_id: str) -> None:
        """Delete a row. The endpoint takes no body and returns no content."""
        await self._request("DELETE", f"{SHOPPING_LIST_BASE}/row/{item_id}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_client.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full gates**

Run: `uv run pytest -q && uv run mypy custom_components/ica && uv run ruff check .`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git add custom_components/ica/api/client.py tests/api/test_client.py
GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git commit -m "feat(api): add row update and delete against the confirmed endpoints"
```

---

### Task 3: Extract the ICA→HA error mapping into a shared module

Pure refactor — no behavior change. The to-do entity (Task 4) needs the same mapping the services use, and importing it out of `services.py` would be the wrong direction.

**Files:**
- Create: `custom_components/ica/errors.py`
- Modify: `custom_components/ica/services.py`
- Test: none new — the existing `tests/test_services.py` reauth and gateway tests must keep passing unchanged, which is the proof this refactor preserved behavior.

**Interfaces:**
- Consumes: `IcaAuthError`, `IcaError`, `IcaGatewayBlockedError`, `DOMAIN`, `ISSUE_GATEWAY_BLOCKED`.
- Produces: `map_ica_errors(hass: HomeAssistant, entry: IcaConfigEntry)` — an async context manager (note: public name, no leading underscore, since it is now shared).

- [ ] **Step 1: Create `custom_components/ica/errors.py`**

```python
"""Shared mapping from ICA API errors onto Home Assistant behavior."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from .api.exceptions import IcaAuthError, IcaError, IcaGatewayBlockedError
from .const import DOMAIN, ISSUE_GATEWAY_BLOCKED

if TYPE_CHECKING:
    from . import IcaConfigEntry


@contextlib.asynccontextmanager
async def map_ica_errors(
    hass: HomeAssistant, entry: IcaConfigEntry
) -> AsyncIterator[None]:
    """Map ICA API errors onto HA behavior: reauth, a repair issue, or a plain error.

    Subclasses are caught BEFORE the base `IcaError`, otherwise the base arm
    would swallow the two cases that need distinct handling.
    """
    try:
        yield
    except IcaAuthError as err:
        entry.async_start_reauth(hass)  # spec §9: hard 401 -> reauth
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    except IcaGatewayBlockedError as err:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_GATEWAY_BLOCKED,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_GATEWAY_BLOCKED,
        )
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key=ISSUE_GATEWAY_BLOCKED
        ) from err
    except IcaError as err:
        raise HomeAssistantError(str(err)) from err
```

- [ ] **Step 2: Update `custom_components/ica/services.py`**

1. Delete the whole `_map_ica_errors` function (the `@contextlib.asynccontextmanager`-decorated one).
2. Add the import: `from .errors import map_ica_errors`.
3. Replace all three `async with _map_ica_errors(hass, entry):` occurrences with `async with map_ica_errors(hass, entry):`.
4. Remove imports that are now unused. Run `uv run ruff check custom_components` — it reports each unused import (F401) by name; expect at least `contextlib`, `AsyncIterator`, `issue_registry as ir`, `IcaAuthError`, `IcaGatewayBlockedError`, and `ISSUE_GATEWAY_BLOCKED`. Remove exactly what ruff flags — do not guess and do not remove anything still in use.

- [ ] **Step 3: Verify behavior is unchanged**

Run: `uv run pytest tests/test_services.py -v`
Expected: ALL pass unchanged — in particular `test_service_auth_error_triggers_reauth` and `test_service_gateway_blocked_creates_repair_issue`. These are the regression proof for this refactor; if either fails, the extraction changed behavior.

- [ ] **Step 4: Run the full gates**

Run: `uv run pytest -q && uv run mypy custom_components/ica && uv run ruff check .`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git add custom_components/ica/errors.py custom_components/ica/services.py
GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git commit -m "refactor: share the ICA error mapping between services and platforms"
```

---

### Task 4: The to-do list entity

**Files:**
- Create: `custom_components/ica/todo.py`
- Modify: `custom_components/ica/const.py` (`PLATFORMS`)
- Test: `tests/test_todo.py`

**Interfaces:**
- Consumes: `IcaClient.add_item/update_item/remove_item` (Task 2), `ShoppingListItem` + `to_updated_row` (Task 1), `map_ica_errors` (Task 3), `IcaDataUpdateCoordinator` (`.data`, `.list_id`, `.async_request_refresh()`), `entry.runtime_data` (`.client`, `.coordinator`), `CONF_LIST_TITLE`.
- Produces: `IcaTodoListEntity`; the `todo` platform for this integration.

- [ ] **Step 1: Turn the platform on** — in `custom_components/ica/const.py`

```python
PLATFORMS: list[Platform] = [Platform.TODO]
```

(replacing the empty list; `Platform` is already imported.)

- [ ] **Step 2: Write the failing tests** — create `tests/test_todo.py`

```python
"""Tests for the ICA to-do list entity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.models import ShoppingList, ShoppingListItem
from custom_components.ica.const import (
    CONF_LIST_ID,
    CONF_LIST_TITLE,
    CONF_TOKEN,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

REFRESH = "custom_components.ica.coordinator.IcaDataUpdateCoordinator.async_request_refresh"


def _token_dict() -> dict[str, str]:
    return IcaToken(
        "a", "r", datetime.now(UTC) + timedelta(hours=1), "c", "s", "sc"
    ).to_dict()


async def _setup(hass: HomeAssistant, items: list[ShoppingListItem]) -> str:
    """Set the integration up and return the to-do entity id."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TOKEN: _token_dict(),
            CONF_LIST_ID: "G1",
            CONF_LIST_TITLE: "Inköpslista",
        },
        entry_id="e1",
    )
    entry.add_to_hass(hass)
    lst = ShoppingList(id="G1", name="Inköpslista", items=items)
    with patch("custom_components.ica.IcaClient.get_list", AsyncMock(return_value=lst)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entity_ids = hass.states.async_entity_ids("todo")
    assert entity_ids, "no todo entity was created"
    return entity_ids[0]


async def test_entity_exposes_rows_as_items(hass: HomeAssistant) -> None:
    entity_id = await _setup(
        hass,
        [
            ShoppingListItem("R1", "Mjölk", False),
            ShoppingListItem("R2", "Bröd", True),
        ],
    )
    state = hass.states.get(entity_id)
    assert state is not None
    # A to-do entity's state is its count of not-yet-done items.
    assert state.state == "1"

    result = await hass.services.async_call(
        "todo",
        "get_items",
        {},
        target={"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    items = result[entity_id]["items"]
    by_summary = {i["summary"]: i for i in items}
    assert by_summary["Mjölk"]["status"] == "needs_action"
    assert by_summary["Bröd"]["status"] == "completed"
    assert by_summary["Mjölk"]["uid"] == "R1"


async def test_create_item_does_not_dedupe(hass: HomeAssistant) -> None:
    # UI/voice adds always add, unlike the scanner services (spec §6).
    entity_id = await _setup(hass, [ShoppingListItem("R1", "Mjölk", False)])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.add_item", AsyncMock()
        ) as add,
        patch(REFRESH, AsyncMock()) as refresh,
    ):
        await hass.services.async_call(
            "todo",
            "add_item",
            {"item": "Mjölk"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    add.assert_awaited_once_with("G1", "Mjölk")
    refresh.assert_awaited_once()


async def test_check_off_item_preserves_the_rest_of_the_row(
    hass: HomeAssistant,
) -> None:
    row = ShoppingListItem.from_api(
        {
            "id": "R1",
            "text": "Mjölk",
            "isStriked": False,
            "article": {"id": 11103, "group": {"id": 10}},
        }
    )
    entity_id = await _setup(hass, [row])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.update_item", AsyncMock()
        ) as update,
        patch(REFRESH, AsyncMock()) as refresh,
    ):
        await hass.services.async_call(
            "todo",
            "update_item",
            {"item": "Mjölk", "status": "completed"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    args, kwargs = update.await_args
    assert args[0].id == "R1"
    # The client is handed the ROW, so the untouched fields ride along.
    assert args[0].raw["article"] == {"id": 11103, "group": {"id": 10}}
    assert kwargs["is_checked"] is True
    refresh.assert_awaited_once()


async def test_rename_item(hass: HomeAssistant) -> None:
    entity_id = await _setup(hass, [ShoppingListItem("R1", "mjolk", False)])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.update_item", AsyncMock()
        ) as update,
        patch(REFRESH, AsyncMock()),
    ):
        await hass.services.async_call(
            "todo",
            "update_item",
            {"item": "mjolk", "rename": "Mjölk"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    _, kwargs = update.await_args
    assert kwargs["text"] == "Mjölk"


async def test_remove_item(hass: HomeAssistant) -> None:
    entity_id = await _setup(hass, [ShoppingListItem("R1", "Mjölk", False)])
    with (
        patch(
            "custom_components.ica.api.client.IcaClient.remove_item", AsyncMock()
        ) as remove,
        patch(REFRESH, AsyncMock()) as refresh,
    ):
        await hass.services.async_call(
            "todo",
            "remove_item",
            {"item": "Mjölk"},
            target={"entity_id": entity_id},
            blocking=True,
        )
    remove.assert_awaited_once_with("R1")
    refresh.assert_awaited_once()
```

> **If a `todo` service's field names differ on the installed HA 2025.4.4** (check `.venv/lib/python3.13/site-packages/homeassistant/components/todo/services.yaml`), adapt the call — but keep every assertion: what is being verified (no dedupe on create, the full row reaching the client, rename, delete, and a refresh after each write) must not be weakened.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_todo.py -q`
Expected: FAIL — `assert entity_ids, "no todo entity was created"` (the platform does not exist yet).

- [ ] **Step 4: Implement** — create `custom_components/ica/todo.py`

```python
"""The ICA shopping list as a Home Assistant to-do list entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import ShoppingListItem
from .const import CONF_LIST_TITLE
from .coordinator import IcaDataUpdateCoordinator
from .errors import map_ica_errors

if TYPE_CHECKING:
    from . import IcaConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IcaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the ICA to-do list entity."""
    async_add_entities([IcaTodoListEntity(entry)])


class IcaTodoListEntity(CoordinatorEntity[IcaDataUpdateCoordinator], TodoListEntity):
    """The configured ICA shopping list, as a to-do list."""

    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(self, entry: IcaConfigEntry) -> None:
        """Initialise the entity from the config entry's runtime data."""
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        self._client = entry.runtime_data.client
        # The entity id is slugified from this name, so the "ICA " prefix is
        # what produces `todo.ica_<list>` rather than a bare `todo.<list>`.
        title = entry.data.get(CONF_LIST_TITLE) or "shopping list"
        self._attr_name = f"ICA {title}"
        self._attr_unique_id = f"{entry.entry_id}_{self.coordinator.list_id}"

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return the list's rows, or None while the list is unavailable."""
        if self.coordinator.data is None:
            return None
        return [
            TodoItem(
                uid=row.id,
                summary=row.text,
                status=(
                    TodoItemStatus.COMPLETED
                    if row.is_checked
                    else TodoItemStatus.NEEDS_ACTION
                ),
            )
            for row in self.coordinator.data.items
        ]

    def _row(self, uid: str) -> ShoppingListItem:
        """Return the current row for `uid`.

        The row carries the full payload the update endpoint needs, so edits
        must go through it rather than through a reconstructed item.
        """
        data = self.coordinator.data
        for row in data.items if data is not None else []:
            if row.id == uid:
                return row
        raise HomeAssistantError(f"ICA list item {uid} no longer exists")

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item. Deliberately NOT deduped — see spec §6."""
        async with map_ica_errors(self.hass, self._entry):
            await self._client.add_item(self.coordinator.list_id, item.summary or "")
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Rename and/or check off an item, preserving the rest of its row."""
        async with map_ica_errors(self.hass, self._entry):
            row = self._row(item.uid or "")
            await self._client.update_item(
                row,
                text=item.summary,
                is_checked=item.status == TodoItemStatus.COMPLETED,
            )
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items (the card's 'remove completed items' sends several)."""
        async with map_ica_errors(self.hass, self._entry):
            for uid in uids:
                await self._client.remove_item(uid)
        await self.coordinator.async_request_refresh()
```

> If `AddConfigEntryEntitiesCallback` does not exist in the installed HA, use `AddEntitiesCallback` from the same module instead — check `.venv/lib/python3.13/site-packages/homeassistant/helpers/entity_platform.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_todo.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full gates**

Run: `uv run pytest -q && uv run mypy custom_components/ica && uv run ruff check . && uv run ruff format --check .`
Expected: all green. `tests/test_init.py::test_setup_and_unload` must still pass — it now also exercises forwarding to a real platform.

- [ ] **Step 7: Commit**

```bash
GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git add custom_components/ica/todo.py custom_components/ica/const.py tests/test_todo.py
GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git commit -m "feat: add the ICA shopping list as a to-do list entity"
```

---

## Manual verification (after all tasks — needs the real account)

The unit tests mock HTTP, so the round-trip against ICA is only proven on the device:

1. `./scripts/deploy.sh` (syncs and restarts HA).
2. Add the **To-do list** card for the new `todo.*` entity, or open Settings → the ICA integration.
3. Confirm the card lists your items, with bought ones shown as completed.
4. **Check an item off in HA → open the ICA app → confirm it is struck through AND still sits in its correct category/aisle.** This is the full-row preservation working; if the item jumps to "Ospecificerad" or loses its place, `to_updated_row` is dropping `article`.
5. Add an item in HA → appears in the ICA app. Add the same text again → it is added a second time (no dedupe, by design).
6. Rename an item in HA → the ICA app shows the new text.
7. Delete an item, and use the card's "remove completed items" → gone from the ICA app.
8. Say "add bröd to Inköpslista" to Assist → it appears.

## Notes for the executor

- The one genuinely risky thing here is the full-row `PUT`. If ICA rejects an update or an item loses its category, capture the outgoing body and diff it against the row `GET .../list/all` returned — a missing or reshaped key is the likely cause.
- Do NOT add dedupe to the entity's create path. The asymmetry with the scanner services is deliberate and documented.
- Do NOT implement `MOVE_TODO_ITEM`, due dates, or descriptions. ICA rows have no such concepts and the spec excludes them.
