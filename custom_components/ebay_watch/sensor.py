"""eBay Watch sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import EbayConfigEntry
from .const import DOMAIN
from .coordinator import EbayCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: EbayConfigEntry, add: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    add([WatchlistSensor(c), NextEndingSensor(c), InTransitSensor(c)])


class EbaySensor(CoordinatorEntity[EbayCoordinator], SensorEntity):
    _attr_has_entity_name = True
    key = ""

    def __init__(self, coordinator: EbayCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{self.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="eBay", manufacturer="eBay",
            model=entry.title, entry_type=DeviceEntryType.SERVICE,
        )


class WatchlistSensor(EbaySensor):
    key = "watchlist"
    _attr_name = "Watchlist"
    _attr_icon = "mdi:eye"
    _attr_native_unit_of_measurement = "items"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"items"})

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.watchlist)

    @property
    def extra_state_attributes(self) -> dict:
        return {"items": self.coordinator.data.watchlist}


class NextEndingSensor(EbaySensor):
    key = "next_ending"
    _attr_name = "Next ending"
    _attr_icon = "mdi:timer-sand"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def _next(self) -> dict | None:
        now = dt_util.utcnow()
        live = [(dt_util.parse_datetime(i["end_time"]), i) for i in self.coordinator.data.watchlist if i["end_time"]]
        live = [x for x in live if x[0] and x[0] > now]
        return min(live, key=lambda x: x[0])[1] if live else None

    @property
    def native_value(self):
        item = self._next()
        return dt_util.parse_datetime(item["end_time"]) if item else None

    @property
    def extra_state_attributes(self) -> dict:
        item = self._next() or {}
        return {k: item.get(k) for k in ("item_id", "title", "price", "currency", "bids", "url", "image")}


class InTransitSensor(EbaySensor):
    key = "in_transit"
    _attr_name = "Packages in transit"
    _attr_icon = "mdi:truck-delivery"
    _attr_native_unit_of_measurement = "packages"
    _unrecorded_attributes = frozenset({"orders"})

    @property
    def native_value(self) -> int:
        return sum(1 for o in self.coordinator.data.orders if o["tracking"] and not o["delivered"])

    @property
    def extra_state_attributes(self) -> dict:
        orders = self.coordinator.data.orders
        active = [o for o in orders if o["status"] != "Cancelled"]
        return {
            "awaiting_shipment": sum(1 for o in active if not o["tracking"] and not o["delivered"]),
            "delivered": sum(1 for o in active if o["delivered"]),
            "orders": orders,
        }
