"""The ICA shopping list as a Home Assistant to-do list entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.todo import TodoItem, TodoListEntity
from homeassistant.components.todo.const import TodoItemStatus, TodoListEntityFeature
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

        This row comes from the coordinator's cached snapshot, not a fresh
        fetch: an edit PUTs back whatever the last poll saw, so it can revert
        changes made in the ICA app since then. Accepted deliberately -
        fetching fresh on every card edit would make the card sluggish.
        Contrast with `services.py::_resolve_list`, which always reads fresh
        because a barcode scan has no display to show stale state on.
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
                is_checked=(
                    None
                    if item.status is None
                    else item.status == TodoItemStatus.COMPLETED
                ),
            )
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items (the card's 'remove completed items' sends several).

        The refresh runs in `finally` so a mid-loop failure still surfaces the
        deletes that DID succeed, instead of hiding them until the next poll.
        """
        try:
            async with map_ica_errors(self.hass, self._entry):
                for uid in uids:
                    await self._client.remove_item(uid)
        finally:
            await self.coordinator.async_request_refresh()
