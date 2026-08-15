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
