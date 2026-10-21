"""eBay Watch: watchlist, alerts, and purchase tracking for Home Assistant."""
from __future__ import annotations

from pathlib import Path

import voluptuous as vol
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .api import EbayAuthError, EbayClient
from .const import CARD_URL, CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REFRESH_TOKEN, CONF_SANDBOX, DOMAIN, LOGGER, VERSION
from .coordinator import FETCH_ERRORS, EbayCoordinator

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
ATTR_ENTRY = "config_entry_id"

type EbayConfigEntry = ConfigEntry[EbayCoordinator]


def _coordinators(hass: HomeAssistant, call: ServiceCall) -> list[EbayCoordinator]:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if entry_id := call.data.get(ATTR_ENTRY):
        entries = [e for e in entries if e.entry_id == entry_id]
    if not entries:
        raise HomeAssistantError("No loaded eBay Watch entry found")
    return [e.runtime_data for e in entries]


async def _async_register_card(hass: HomeAssistant) -> None:
    """Keep exactly one Lovelace resource for the card, versioned to the installed release."""
    url = f"{CARD_URL}?v={VERSION}"
    data = hass.data.get("lovelace")
    resources = getattr(data, "resources", None)
    if resources is None and isinstance(data, dict):
        resources = data.get("resources")
    if resources is None or not hasattr(resources, "async_create_item"):
        LOGGER.warning("Dashboards are in YAML mode; add %s as a JavaScript module resource manually", url)
        return
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True
    existing = [r for r in resources.async_items() if r.get("url", "").split("?")[0] == CARD_URL]
    if not existing:
        await resources.async_create_item({"res_type": "module", "url": url})
        LOGGER.info("Registered dashboard resource %s", url)
        return
    first, *dupes = existing
    if first["url"] != url or first.get("type") != "module":
        await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
        LOGGER.info("Updated dashboard resource to %s", url)
    for dupe in dupes:
        await resources.async_delete_item(dupe["id"])


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(Path(__file__).parent / "frontend" / "ebay-watch-card.js"), False)]
    )

    async def _register(_hass: HomeAssistant) -> None:
        try:
            await _async_register_card(hass)
        except Exception:  # noqa: BLE001 - never block setup over the card
            LOGGER.exception("Could not register the eBay Watch dashboard resource")

    async_at_started(hass, _register)

    async def remove(call: ServiceCall) -> None:
        coord = _coordinators(hass, call)[0]
        try:
            await coord.async_remove(call.data["item_id"])
        except EbayAuthError as err:
            coord.config_entry.async_start_reauth(hass)
            raise HomeAssistantError("eBay authorization expired — reauthenticate the integration") from err
        except FETCH_ERRORS as err:
            raise HomeAssistantError(f"eBay: {err}") from err

    async def refresh(call: ServiceCall) -> None:
        for coord in _coordinators(hass, call):
            await coord.async_request_refresh()

    hass.services.async_register(DOMAIN, "remove_from_watchlist", remove, schema=vol.Schema({
        vol.Required("item_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_ENTRY): cv.string,
    }))
    hass.services.async_register(DOMAIN, "refresh", refresh, schema=vol.Schema({vol.Optional(ATTR_ENTRY): cv.string}))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EbayConfigEntry) -> bool:
    client = EbayClient(
        async_get_clientsession(hass), entry.data[CONF_CLIENT_ID], entry.data[CONF_CLIENT_SECRET],
        entry.data[CONF_REFRESH_TOKEN], entry.data.get(CONF_SANDBOX, False),
    )
    coordinator = EbayCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: EbayConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EbayConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
