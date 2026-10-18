"""Minimal async eBay client: OAuth refresh-token flow + Trading API (XML)."""
from __future__ import annotations

import asyncio
import base64
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

import aiohttp

NS = {"e": "urn:ebay:apis:eBLBaseComponents"}
COMPAT_LEVEL = "1423"
SITE_ID = "0"  # US
SCOPES = "https://api.ebay.com/oauth/api_scope"
AUTH_ERROR_CODES = {"931", "932", "16110", "17470", "21916984", "21917053"}

CARRIER_URLS = {
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={}",
    "UPS": "https://www.ups.com/track?tracknum={}",
    "FEDEX": "https://www.fedex.com/fedextrack/?trknbr={}",
    "DHL": "https://www.dhl.com/us-en/home/tracking/tracking-express.html?tracking-id={}",
    "ONTRAC": "https://www.ontrac.com/tracking/?number={}",
}


class EbayError(Exception):
    """Generic eBay API failure."""


class EbayAuthError(EbayError):
    """Refresh token / user token rejected."""


def tracking_url(carrier: str, number: str) -> str:
    key = (carrier or "").upper().replace(" ", "")
    for prefix, url in CARRIER_URLS.items():
        if key.startswith(prefix):
            return url.format(number)
    return f"https://www.google.com/search?q={number}"


def _t(el: ET.Element, path: str, default=None):
    val = el.findtext(path, None, NS)
    return val if val is not None else default


def _money(el: ET.Element, path: str) -> tuple[float | None, str | None]:
    node = el.find(path, NS)
    if node is None or not node.text:
        return None, None
    return float(node.text), node.get("currencyID")


def _parse_watch_item(i: ET.Element) -> dict:
    item_id = _t(i, "e:ItemID")
    price, currency = _money(i, "e:SellingStatus/e:CurrentPrice")
    shipping, _ = _money(i, "e:ShippingDetails/e:ShippingServiceOptions/e:ShippingServiceCost")
    variation = {
        nv.findtext("e:Name", "", NS): nv.findtext("e:Value", "", NS)
        for nv in i.findall("e:Variation/e:VariationSpecifics/e:NameValueList", NS)
    }
    return {
        "item_id": item_id,
        "title": _t(i, "e:Title", ""),
        "price": price,
        "currency": currency,
        "shipping": shipping,
        "bids": int(_t(i, "e:SellingStatus/e:BidCount", "0")),
        "listing_type": _t(i, "e:ListingType"),
        "status": _t(i, "e:SellingStatus/e:ListingStatus"),
        "end_time": _t(i, "e:ListingDetails/e:EndTime"),
        "url": _t(i, "e:ListingDetails/e:ViewItemURL", f"https://www.ebay.com/itm/{item_id}"),
        "image": _t(i, "e:PictureDetails/e:GalleryURL"),
        "seller": _t(i, "e:Seller/e:UserID"),
        "variation": variation or None,
    }


def _parse_order(o: ET.Element) -> dict:
    total, currency = _money(o, "e:Total")
    items, tracking, seen = [], [], set()
    for tx in o.findall("e:TransactionArray/e:Transaction", NS):
        items.append({
            "item_id": _t(tx, "e:Item/e:ItemID"),
            "title": _t(tx, "e:Item/e:Title", ""),
            "qty": int(_t(tx, "e:QuantityPurchased", "1")),
        })
        for d in tx.findall("e:ShippingDetails/e:ShipmentTrackingDetails", NS):
            num = _t(d, "e:ShipmentTrackingNumber")
            if num and num not in seen:
                seen.add(num)
                carrier = _t(d, "e:ShippingCarrierUsed", "")
                tracking.append({"carrier": carrier, "number": num, "url": tracking_url(carrier, num)})
    return {
        "order_id": _t(o, "e:OrderID"),
        "status": _t(o, "e:OrderStatus"),
        "created": _t(o, "e:CreatedTime"),
        "paid": _t(o, "e:PaidTime"),
        "shipped": _t(o, "e:ShippedTime"),
        "delivered": _t(o, ".//e:ShippingPackageInfo/e:ActualDeliveryTime"),
        "est_delivery": _t(o, ".//e:ShippingPackageInfo/e:EstimatedDeliveryTimeMax"),
        "seller": _t(o, "e:SellerUserID"),
        "total": total,
        "currency": currency,
        "items": items,
        "tracking": tracking,
    }


class EbayClient:
    def __init__(self, session: aiohttp.ClientSession, client_id: str, client_secret: str,
                 refresh_token: str, sandbox: bool = False) -> None:
        host = "api.sandbox.ebay.com" if sandbox else "api.ebay.com"
        self._token_url = f"https://{host}/identity/v1/oauth2/token"
        self._trading_url = f"https://{host}/ws/api.dll"
        self._session = session
        self._basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def _token(self, force: bool = False) -> str:
        async with self._lock:
            if force or not self._access_token or time.monotonic() >= self._expires:
                async with self._session.post(
                    self._token_url,
                    headers={"Authorization": f"Basic {self._basic}"},
                    data={"grant_type": "refresh_token", "refresh_token": self._refresh_token, "scope": SCOPES},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.json(content_type=None)
                    status = resp.status
                if status != 200:
                    msg = f"{body.get('error')}: {body.get('error_description')}"
                    if body.get("error") in ("invalid_grant", "invalid_client", "invalid_scope"):
                        raise EbayAuthError(msg)
                    raise EbayError(f"Token refresh failed ({status}) {msg}")
                self._access_token = body["access_token"]
                self._expires = time.monotonic() + int(body.get("expires_in", 7200)) - 300
            return self._access_token

    async def _call(self, call: str, body: str = "", retry: bool = True) -> ET.Element:
        payload = f'<?xml version="1.0" encoding="utf-8"?><{call}Request xmlns="{NS["e"]}">{body}</{call}Request>'
        headers = {
            "X-EBAY-API-CALL-NAME": call,
            "X-EBAY-API-SITEID": SITE_ID,
            "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT_LEVEL,
            "X-EBAY-API-IAF-TOKEN": await self._token(),
            "Content-Type": "text/xml",
        }
        async with self._session.post(self._trading_url, data=payload.encode(), headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=30)) as resp:
            root = ET.fromstring(await resp.read())
        if _t(root, "e:Ack") in ("Success", "Warning"):
            return root
        errors = [
            (e.findtext("e:ErrorCode", "", NS), e.findtext("e:LongMessage", "", NS) or e.findtext("e:ShortMessage", "", NS))
            for e in root.findall("e:Errors", NS)
            if e.findtext("e:SeverityCode", "Error", NS) == "Error"
        ]
        msg = "; ".join(f"[{c}] {m}" for c, m in errors) or "Unknown eBay error"
        if any(code in AUTH_ERROR_CODES for code, _ in errors):
            if retry:
                await self._token(force=True)
                return await self._call(call, body, retry=False)
            raise EbayAuthError(msg)
        raise EbayError(f"{call}: {msg}")

    async def get_user_id(self) -> str:
        return _t(await self._call("GetUser"), "e:User/e:UserID")

    async def get_watchlist(self) -> list[dict]:
        items, page, pages = [], 1, 1
        while page <= pages:
            root = await self._call(
                "GetMyeBayBuying",
                "<WatchList><Include>true</Include><Sort>EndTime</Sort>"
                f"<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>"
                "</WatchList>",
            )
            wl = root.find("e:WatchList", NS)
            if wl is None:
                break
            pages = int(_t(wl, "e:PaginationResult/e:TotalNumberOfPages", "1"))
            items += [_parse_watch_item(i) for i in wl.findall("e:ItemArray/e:Item", NS)]
            page += 1
        return items

    async def remove_from_watchlist(self, items: list[dict]) -> None:
        plain = [i for i in items if not i.get("variation")]
        varied = [i for i in items if i.get("variation")]
        if plain:
            await self._call("RemoveFromWatchList", "".join(f"<ItemID>{escape(i['item_id'])}</ItemID>" for i in plain))
        if varied:
            keys = "".join(
                f"<VariationKey><ItemID>{escape(i['item_id'])}</ItemID><VariationSpecifics>"
                + "".join(f"<NameValueList><Name>{escape(k)}</Name><Value>{escape(v)}</Value></NameValueList>"
                          for k, v in i["variation"].items())
                + "</VariationSpecifics></VariationKey>"
                for i in varied
            )
            await self._call("RemoveFromWatchList", keys)

    async def get_orders(self, days: int) -> list[dict]:
        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%S.000Z"
        start = (now - timedelta(days=min(days, 90))).strftime(fmt)
        orders, page, more = [], 1, True
        while more:
            root = await self._call(
                "GetOrders",
                f"<OrderRole>Buyer</OrderRole><OrderStatus>All</OrderStatus>"
                f"<CreateTimeFrom>{start}</CreateTimeFrom><CreateTimeTo>{now.strftime(fmt)}</CreateTimeTo>"
                f"<DetailLevel>ReturnAll</DetailLevel>"
                f"<Pagination><EntriesPerPage>100</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>",
            )
            orders += [_parse_order(o) for o in root.findall("e:OrderArray/e:Order", NS)]
            more = _t(root, "e:HasMoreOrders") == "true"
            page += 1
        return sorted(orders, key=lambda o: o["created"] or "", reverse=True)
