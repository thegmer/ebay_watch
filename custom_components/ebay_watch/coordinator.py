"""Polling coordinator + alert event detection."""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EbayAuthError, EbayClient, EbayError
from .const import (
    CONF_ENDING_SOON, CONF_ORDER_DAYS, CONF_SCAN_INTERVAL, DEFAULT_ENDING_SOON, DEFAULT_ORDER_DAYS,
    DEFAULT_SCAN_INTERVAL, DOMAIN, EVENT_DELIVERED, EVENT_ENDING_SOON, EVENT_PRICE_DROP,
    EVENT_TRACKING_ADDED, LOGGER,
)

FETCH_ERRORS = (EbayError, aiohttp.ClientError, asyncio.TimeoutError, ET.ParseError)


@dataclass
class EbayData:
    watchlist: list[dict]
    orders: list[dict]


def _brief(item: dict) -> dict:
    return {k: item.get(k) for k in ("item_id", "title", "price", "currency", "url", "image", "end_time")}


class EbayCoordinator(DataUpdateCoordinator[EbayData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: EbayClient) -> None:
        super().__init__(
            hass, LOGGER, config_entry=entry, name=DOMAIN,
            update_interval=timedelta(minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.client = client
        self._store: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._seen: dict | None = None

    def _opt(self, key: str, default: int) -> int:
        return self.config_entry.options.get(key, default)

    async def _async_update_data(self) -> EbayData:
        if self._seen is None:
            self._seen = await self._store.async_load() or {}
        try:
            watchlist, orders = await asyncio.gather(
                self.client.get_watchlist(),
                self.client.get_orders(self._opt(CONF_ORDER_DAYS, DEFAULT_ORDER_DAYS)),
            )
        except EbayAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FETCH_ERRORS as err:
            raise UpdateFailed(str(err)) from err
        self._detect_alerts(watchlist, orders)
        await self._store.async_save(self._seen)
        return EbayData(watchlist, orders)

    def _detect_alerts(self, watchlist: list[dict], orders: list[dict]) -> None:
        """Fire events on changes. First run ever only seeds state (no event burst on install)."""
        seen = self._seen or {}
        first = not seen
        fire = (lambda *a: None) if first else self.hass.bus.async_fire
        prices: dict = seen.get("prices", {})
        alerted = set(seen.get("ending_alerted", []))
        tracked = set(seen.get("tracking", []))
        delivered = set(seen.get("delivered", []))
        now = dt_util.utcnow()
        threshold = timedelta(minutes=self._opt(CONF_ENDING_SOON, DEFAULT_ENDING_SOON))

        for item in watchlist:
            iid, price = item["item_id"], item["price"]
            old = prices.get(iid)
            if old is not None and price is not None and price < old:
                fire(EVENT_PRICE_DROP, {**_brief(item), "old_price": old, "drop": round(old - price, 2)})
            end = dt_util.parse_datetime(item["end_time"]) if item["end_time"] else None
            if end and now < end <= now + threshold and iid not in alerted:
                alerted.add(iid)
                fire(EVENT_ENDING_SOON, {**_brief(item), "bids": item["bids"],
                                         "minutes_left": int((end - now).total_seconds() // 60)})

        numbers, order_ids = set(), set()
        for order in orders:
            order_ids.add(order["order_id"])
            title = order["items"][0]["title"] if order["items"] else order["order_id"]
            base = {"order_id": order["order_id"], "title": title, "seller": order["seller"]}
            for trk in order["tracking"]:
                numbers.add(trk["number"])
                if trk["number"] not in tracked:
                    tracked.add(trk["number"])
                    fire(EVENT_TRACKING_ADDED, {**base, **trk})
            if order["delivered"] and order["order_id"] not in delivered:
                delivered.add(order["order_id"])
                fire(EVENT_DELIVERED, {**base, "delivered": order["delivered"]})

        live = {i["item_id"] for i in watchlist}
        self._seen = {
            "prices": {i["item_id"]: i["price"] for i in watchlist if i["price"] is not None},
            "ending_alerted": sorted(alerted & live),
            "tracking": sorted(tracked & numbers),
            "delivered": sorted(delivered & order_ids),
        }

    async def async_remove(self, item_ids: list[str]) -> None:
        current = self.data.watchlist if self.data else []
        lookup = {i["item_id"]: i for i in current}
        await self.client.remove_from_watchlist([lookup.get(i, {"item_id": i}) for i in item_ids])
        if self.data:
            self.async_set_updated_data(
                EbayData([i for i in current if i["item_id"] not in item_ids], self.data.orders)
            )
