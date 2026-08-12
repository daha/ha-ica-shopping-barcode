"""Tests for the ICA config flow."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, patch

from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.models import ShoppingList
from custom_components.ica.const import (
    CONF_LIST_ID,
    CONF_PASSWORD,
    CONF_PERSONNUMMER,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


def _token() -> IcaToken:
    from datetime import datetime, timedelta

    return IcaToken("a", "r", datetime.now(UTC) + timedelta(hours=1), "c", "s", "sc")


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
