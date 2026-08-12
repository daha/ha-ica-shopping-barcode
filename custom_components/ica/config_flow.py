"""Placeholder config flow; the real flow (setup + reauth + options) lands in Task 6.

`manifest.json` declares `config_flow: true`, and Home Assistant requires an
importable `ConfigFlow` handler registered for the domain before it will set up
*any* config entry for this integration (even in tests that never open the UI
flow). This minimal placeholder exists solely to satisfy that requirement early;
Task 6 replaces it with the real implementation.
"""

from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN


class IcaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Placeholder handler; Task 6 replaces this with the real flow."""

    VERSION = 1
