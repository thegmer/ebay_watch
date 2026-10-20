# eBay Watch for Home Assistant

Custom integration that polls your eBay account and gives you:

- **Watchlist**: price, shipping, bids, live countdown, and an unwatch button on each listing
- **Alerts** as HA events: ending soon, price drop, tracking number posted, delivered
- **Purchases**: the last 1–90 days of orders, with carrier tracking numbers and links
- A bundled dashboard card (`custom:ebay-watch-card`), served by the integration

It uses the eBay **Trading API** (`GetMyeBayBuying`, `RemoveFromWatchList`, `GetOrders` with `OrderRole=Buyer`), authenticated with an OAuth user token. The modern REST APIs don't expose the watchlist.

## 1. eBay developer setup (one time)

1. Sign up at developer.ebay.com, then create a **Production** keyset under *Application Keysets*.
2. eBay won't activate production keys until you deal with *Marketplace Account Deletion* notifications. For a personal app that doesn't keep other users' data, choose the exemption option.
3. Open *User Tokens*, pick **OAuth**, and set up a RuName if prompted. The accept/decline URLs can be any HTTPS page, because the portal shows you the token itself.
4. Click **Sign in to Production for OAuth** and sign in with your eBay buyer account. Copy the **Refresh Token**, which is valid for about 18 months.
5. From the keyset, note the **App ID** (Client ID) and **Cert ID** (Client Secret).

## 2. Install

Copy `custom_components/ebay_watch` to `/config/custom_components/`, or add this repo to HACS as a custom repository. Restart HA, then go to *Settings → Devices & services → Add integration → eBay Watch* and paste the three values.

Then register the dashboard card: **Settings → Dashboards → ⋮ → Resources → Add resource**, URL `/ebay_watch/ebay-watch-card.js?v=0.1.2`, type **JavaScript module**, and hard refresh (Ctrl+F5). Bump the `?v=` value whenever you update the integration.

Options (configure on the integration): poll interval (default 10 min), ending-soon threshold (default 60 min), and order lookback (default 30 days).

## Entities

| Entity | State | Attributes |
|---|---|---|
| `sensor.ebay_watchlist` | # items | `items` (full list, not recorded to DB) |
| `sensor.ebay_next_ending` | timestamp | title, price, url, image, bids |
| `sensor.ebay_packages_in_transit` | # with tracking, not delivered | `awaiting_shipment`, `delivered`, `orders` |

## Services

- `ebay_watch.remove_from_watchlist`: `item_id` takes one or a list. Multi-variation listings are handled automatically.
- `ebay_watch.refresh`: polls immediately.

## Events

| Event | Data |
|---|---|
| `ebay_watch_ending_soon` | item_id, title, price, currency, url, image, end_time, bids, minutes_left |
| `ebay_watch_price_drop` | the item fields above, plus old_price and drop |
| `ebay_watch_tracking_added` | order_id, title, seller, carrier, number, url |
| `ebay_watch_delivered` | order_id, title, seller, delivered |

The integration never fires the same event twice for the same item, tracking number, or order. That state persists in `.storage`, so restarts don't re-alert. The very first poll after install only seeds this state. See `examples/` for the dashboard and notification automations, including an actionable **Stop watching** button.

## Notes

- API budget: the default Trading API limit is 5,000 calls/day. At a 10-minute interval this uses roughly 300/day.
- `delivered` and `est_delivery` depend on eBay having carrier scan data. Plenty of orders only ever show tracking.
- If token refresh fails with `invalid_scope`, edit `SCOPES` in `api.py` to match the scopes you granted in the portal.
- When the refresh token expires, HA raises a reauth prompt. Paste a new token there.
