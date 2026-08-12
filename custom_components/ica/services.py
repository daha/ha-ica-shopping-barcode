"""ICA services: lookup_product, add_item, scan_barcode."""

from __future__ import annotations

from typing import Any, cast

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

from .api import IcaClient, IcaError
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
                # The EAN lookup already carries the article group ids, so build
                # the article inline — ICA files the row in the right category.
                article = product.to_row_article()
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
