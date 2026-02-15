"""Constants for the Amber Express integration."""

from typing import Final

DOMAIN: Final = "amber_express"

# API Configuration
API_URL: Final = "https://api.amber.com.au/v1"
API_DEVELOPER_URL: Final = "https://app.amber.com.au/developers/"
WEBSOCKET_URL: Final = "wss://api-ws.amber.com.au"

# WebSocket Configuration
WS_MIN_RECONNECT_DELAY: Final = 5  # seconds
WS_MAX_RECONNECT_DELAY: Final = 60  # seconds
WS_HEARTBEAT_INTERVAL: Final = 30  # seconds
WS_STALE_TIMEOUT: Final = 360  # 6 minutes - reconnect if no price update received

# Forecast configuration
# Maximum value for the Amber API `/current` prices `next` parameter (documented upstream).
MAX_FORECAST_INTERVALS: Final = 2048

# Channel types
CHANNEL_GENERAL: Final = "general"
CHANNEL_FEED_IN: Final = "feed_in"
CHANNEL_CONTROLLED_LOAD: Final = "controlled_load"

# Pricing modes
PRICING_MODE_AEMO: Final = "per_kwh"  # Uses per_kwh
PRICING_MODE_APP: Final = "advanced_price_predicted"  # Uses advanced_price_predicted

# Config keys
CONF_API_TOKEN: Final = "api_token"  # noqa: S105
CONF_FORECAST_INTERVALS: Final = "forecast_intervals"
CONF_SITE_ID: Final = "site_id"
CONF_SITE_NAME: Final = "site_name"
CONF_PRICING_MODE: Final = "pricing_mode"
CONF_ENABLE_WEBSOCKET: Final = "enable_websocket"
CONF_WAIT_FOR_CONFIRMED: Final = "wait_for_confirmed"
CONF_CONFIRMATION_TIMEOUT: Final = "confirmation_timeout"
CONF_DEMAND_WINDOW_PRICE: Final = "demand_window_price"

# Default options
DEFAULT_PRICING_MODE: Final = PRICING_MODE_APP
# 24 hours at 5-min resolution, or 48 hours at 30-min
DEFAULT_FORECAST_INTERVALS: Final = 288
DEFAULT_ENABLE_WEBSOCKET: Final = True
DEFAULT_WAIT_FOR_CONFIRMED: Final = True  # Keep polling until non-estimated price
DEFAULT_CONFIRMATION_TIMEOUT: Final = 45  # seconds to wait for confirmed price
DEFAULT_DEMAND_WINDOW_PRICE: Final = 0.0  # $/kWh penalty during demand window

# Sensor attributes
ATTR_FORECASTS: Final = "forecasts"
ATTR_START_TIME: Final = "start_time"
ATTR_END_TIME: Final = "end_time"
ATTR_PER_KWH: Final = "per_kwh"
ATTR_SPOT_PER_KWH: Final = "spot_per_kwh"
ATTR_ADVANCED_PRICE: Final = "advanced_price_predicted"
ATTR_RENEWABLES: Final = "renewables"
ATTR_SPIKE_STATUS: Final = "spike_status"
ATTR_DESCRIPTOR: Final = "descriptor"
ATTR_ESTIMATE: Final = "estimate"
ATTR_NEM_TIME: Final = "nem_time"
ATTR_DEMAND_WINDOW: Final = "demand_window"
ATTR_TARIFF_PERIOD: Final = "tariff_period"
ATTR_TARIFF_SEASON: Final = "tariff_season"
ATTR_TARIFF_BLOCK: Final = "tariff_block"

# Data source tracking
DATA_SOURCE_POLLING: Final = "polling"
DATA_SOURCE_WEBSOCKET: Final = "websocket"

# Subentry types
SUBENTRY_TYPE_SITE: Final = "site"
