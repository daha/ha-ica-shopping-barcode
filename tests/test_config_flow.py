"""Tests for the ICA config flow."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, patch

from custom_components.ica.api import IcaError
from custom_components.ica.api.auth import IcaToken
from custom_components.ica.api.models import ShoppingList
from custom_components.ica.const import (
    CONF_LIST_ID,
    CONF_LIST_TITLE,
    CONF_PASSWORD,
    CONF_PERSONNUMMER,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry


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
    assert result["data"][CONF_LIST_TITLE] == "Inköpslista"
    assert CONF_TOKEN in result["data"]


async def test_cannot_connect_on_base_ica_error(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with (
        patch(
            "custom_components.ica.config_flow.IcaAuth.login",
            AsyncMock(return_value=_token()),
        ),
        patch(
            "custom_components.ica.config_flow.IcaClient.get_lists",
            AsyncMock(side_effect=IcaError("boom")),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PERSONNUMMER: "199001010000", CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TOKEN: _token().to_dict(),
            CONF_LIST_ID: "G1",
            CONF_LIST_TITLE: "Inköpslista",
        },
        entry_id="entry1",
        unique_id="G1",
    )


async def test_reauth_flow_success(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    new_token = IcaToken("new-a", "new-r", _token().expires_at, "new-c", "new-s", "sc")
    with patch(
        "custom_components.ica.config_flow.IcaAuth.login",
        AsyncMock(return_value=new_token),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PERSONNUMMER: "199001010000", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == new_token.to_dict()


async def test_options_flow_sets_scan_interval(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 10}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 10


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
