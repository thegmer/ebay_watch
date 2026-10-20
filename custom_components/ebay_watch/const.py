"""Constants for eBay Watch."""
import logging

DOMAIN = "ebay_watch"
VERSION = "0.1.1"
LOGGER = logging.getLogger(__package__)

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_SANDBOX = "sandbox"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENDING_SOON = "ending_soon_minutes"
CONF_ORDER_DAYS = "order_lookback_days"

DEFAULT_SCAN_INTERVAL = 10  # minutes
DEFAULT_ENDING_SOON = 60  # minutes
DEFAULT_ORDER_DAYS = 30  # GetOrders allows up to 90

EVENT_ENDING_SOON = "ebay_watch_ending_soon"
EVENT_PRICE_DROP = "ebay_watch_price_drop"
EVENT_TRACKING_ADDED = "ebay_watch_tracking_added"
EVENT_DELIVERED = "ebay_watch_delivered"

CARD_URL = f"/{DOMAIN}/ebay-watch-card.js"
