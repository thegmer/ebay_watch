"""Config flow for eBay Watch."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EbayAuthError, EbayClient
from .const import (
    CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_ENDING_SOON, CONF_ORDER_DAYS, CONF_REFRESH_TOKEN, CONF_SANDBOX,
    CONF_SCAN_INTERVAL, DEFAULT_ENDING_SOON, DEFAULT_ORDER_DAYS, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER,
)
from .coordinator import FETCH_ERRORS

USER_SCHEMA = vol.Schema({
    vol.Required(CONF_CLIENT_ID): str,
    vol.Required(CONF_CLIENT_SECRET): str,
    vol.Required(CONF_REFRESH_TOKEN): str,
    vol.Optional(CONF_SANDBOX, default=False): bool,
})


async def _validate(hass: HomeAssistant, data: dict) -> tuple[str | None, dict]:
    """Return (ebay user id, errors)."""
    client = EbayClient(async_get_clientsession(hass), data[CONF_CLIENT_ID], data[CONF_CLIENT_SECRET],
                        data[CONF_REFRESH_TOKEN].strip(), data.get(CONF_SANDBOX, False))
    try:
        return await client.get_user_id(), {}
    except EbayAuthError:
        return None, {"base": "invalid_auth"}
    except FETCH_ERRORS:
        LOGGER.exception("eBay connection test failed")
        return None, {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        LOGGER.exception("Unexpected error validating eBay credentials")
        return None, {"base": "unknown"}


class EbayWatchConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict = {}
        if user_input is not None:
            user_input[CONF_REFRESH_TOKEN] = user_input[CONF_REFRESH_TOKEN].strip()
            user_id, errors = await _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_id.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"eBay ({user_id})", data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input), errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict = {}
        if user_input is not None:
            data = {**entry.data, CONF_REFRESH_TOKEN: user_input[CONF_REFRESH_TOKEN].strip()}
            user_id, errors = await _validate(self.hass, data)
            if not errors:
                await self.async_set_unique_id(user_id.lower())
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_REFRESH_TOKEN): str}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EbayWatchOptionsFlow()


class EbayWatchOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required(CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                vol.All(vol.Coerce(int), vol.Range(min=2, max=180)),
            vol.Required(CONF_ENDING_SOON, default=o.get(CONF_ENDING_SOON, DEFAULT_ENDING_SOON)):
                vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
            vol.Required(CONF_ORDER_DAYS, default=o.get(CONF_ORDER_DAYS, DEFAULT_ORDER_DAYS)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=90)),
        }))
