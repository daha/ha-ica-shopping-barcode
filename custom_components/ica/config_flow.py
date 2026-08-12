"""Config flow for the ICA integration."""

from __future__ import annotations

from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
        schema = vol.Schema({vol.Required(CONF_LIST_ID): vol.In(self._lists)})
        return self.async_show_form(step_id="pick_list", data_schema=schema)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
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
    def async_get_options_flow(config_entry: Any) -> IcaOptionsFlow:
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
