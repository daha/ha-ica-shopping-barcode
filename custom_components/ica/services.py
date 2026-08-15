"""ICA services: lookup_product, add_item, scan_barcode."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import Product, ShoppingList
from .const import DOMAIN, UNKNOWN_ITEM_PREFIX
from .errors import map_ica_errors

if TYPE_CHECKING:
    from . import IcaConfigEntry, IcaRuntimeData

SERVICE_LOOKUP_PRODUCT = "lookup_product"
SERVICE_ADD_ITEM = "add_item"
SERVICE_SCAN_BARCODE = "scan_barcode"
SERVICE_REFRESH_LIST = "refresh_list"

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
_REFRESH_SCHEMA = vol.Schema({})

_ServiceHandler = Callable[[ServiceCall], Coroutine[Any, Any, ServiceResponse]]


def _get_entry(hass: HomeAssistant) -> IcaConfigEntry:
    """Return the single loaded ICA config entry.

    The manifest declares `single_config_entry`, so at most one ICA entry can
    ever exist; the first LOADED one (if any) IS the entry.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_set_up")


async def _resolve_list(runtime: IcaRuntimeData, list_name: str | None) -> ShoppingList:
    """Return the target list, ALWAYS freshly fetched (one `list/all` call).

    Dedupe must never be decided from the coordinator's cached snapshot: it can
    be up to `scan_interval` minutes old, so an item checked off or deleted in
    the ICA app since the last poll would still look present and the add would
    be silently skipped (`added: false`, nothing written).
    """
    lists = await runtime.client.get_lists()
    if list_name is None:
        list_id = runtime.coordinator.list_id
        for lst in lists:
            if lst.id == list_id:
                return lst
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="list_not_found"
        )
    target_cf = list_name.strip().casefold()
    for lst in lists:
        if lst.name.strip().casefold() == target_cf:
            return lst
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_list",
        translation_placeholders={"name": list_name},
    )


async def _category_of(runtime: IcaRuntimeData, product: Product | None) -> str | None:
    """Resolve a product's coarse article group to clear text, or None.

    Only the coarse `articleGroupId` is resolvable: ICA's article-group table
    holds just the 10 top-level groups, so the finer `expandedArticleGroupId`
    has no name to look up. None means "unknown" — never the real group
    "Ospecificerad", which ICA assigns deliberately.
    """
    if product is None or product.article_group_id is None:
        return None
    groups = await runtime.client.get_article_groups()
    return groups.get(product.article_group_id)


async def _add_deduped(
    runtime: IcaRuntimeData,
    target: ShoppingList,
    name: str,
    article: dict[str, Any] | None = None,
) -> bool:
    """Add an item unless an UNCHECKED case-insensitive name match exists.

    Returns True if it was added, False if it was a duplicate.
    """
    if target.has_active_item(name):
        return False
    await runtime.client.add_item(target.id, name, article=article)
    if target.id == runtime.coordinator.list_id:
        await runtime.coordinator.async_request_refresh()
    return True


def async_setup_services(hass: HomeAssistant) -> None:
    """Register ICA services (idempotent). Called once from `async_setup`."""
    if hass.services.has_service(DOMAIN, SERVICE_LOOKUP_PRODUCT):
        return

    async def lookup_product(call: ServiceCall) -> ServiceResponse:
        ean = call.data[ATTR_BARCODE]
        entry = _get_entry(hass)
        runtime = entry.runtime_data
        async with map_ica_errors(hass, entry):
            product = await runtime.client.get_product(ean)
            category = await _category_of(runtime, product)
        if product is None:
            return {"found": False, "name": None, "ean": ean, "category": None}
        return {"found": True, "name": product.name, "ean": ean, "category": category}

    async def add_item(call: ServiceCall) -> ServiceResponse:
        name = call.data[ATTR_NAME]
        entry = _get_entry(hass)
        runtime = entry.runtime_data
        async with map_ica_errors(hass, entry):
            target = await _resolve_list(runtime, call.data.get(ATTR_LIST))
            added = await _add_deduped(runtime, target, name)
        return {"added": added, "name": name}

    async def scan_barcode(call: ServiceCall) -> ServiceResponse:
        ean = call.data[ATTR_BARCODE]
        entry = _get_entry(hass)
        runtime = entry.runtime_data
        async with map_ica_errors(hass, entry):
            product = await runtime.client.get_product(ean)
            target = await _resolve_list(runtime, call.data.get(ATTR_LIST))
            if product is not None:
                name = product.name
                found = True
                # The EAN lookup already carries the article group ids, so build
                # the article inline — ICA files the row in the right category.
                article = product.to_row_article()
            else:
                name = f"{UNKNOWN_ITEM_PREFIX} {ean}"
                found = False
                article = None
            added = await _add_deduped(runtime, target, name, article=article)
            category = await _category_of(runtime, product)
        return {
            "found": found,
            "added": added,
            "name": name,
            "ean": ean,
            "category": category,
        }

    async def refresh_list(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass)
        coordinator = entry.runtime_data.coordinator
        # The IMMEDIATE refresh, not the debounced `async_request_refresh`:
        # this service exists precisely to bypass any waiting. Going through
        # the coordinator keeps the repair-issue and reauth handling in
        # `_async_update_data`.
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            # `async_refresh` only logs failures, and a force-refresh that
            # silently does nothing is the very problem this service solves.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_failed",
                translation_placeholders={
                    "error": str(coordinator.last_exception or "unknown error")
                },
            )
        data = coordinator.data
        return {
            "list": data.name,
            "items": len(data.items),
            "unchecked": sum(1 for item in data.items if not item.is_checked),
        }

    services: tuple[tuple[str, _ServiceHandler, vol.Schema], ...] = (
        (SERVICE_LOOKUP_PRODUCT, lookup_product, _LOOKUP_SCHEMA),
        (SERVICE_ADD_ITEM, add_item, _ADD_SCHEMA),
        (SERVICE_SCAN_BARCODE, scan_barcode, _SCAN_SCHEMA),
        (SERVICE_REFRESH_LIST, refresh_list, _REFRESH_SCHEMA),
    )
    for name, handler, schema in services:
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
