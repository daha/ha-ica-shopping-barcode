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
