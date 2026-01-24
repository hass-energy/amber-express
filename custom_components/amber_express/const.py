"""Constants for the Amber Express integration."""

from typing import Final

DOMAIN: Final = "amber_express"

# API Configuration
API_URL: Final = "https://api.amber.com.au/v1"
WEBSOCKET_URL: Final = "wss://api-ws.amber.com.au"

# Polling Configuration - inspired by amber2mqtt
# Poll at specific seconds within the first 2 minutes of each 5-minute interval
POLL_SECONDS: Final = (14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 35, 40, 45, 50, 55)
POLL_MINUTES: Final = (0, 1, 5, 6, 10, 11, 15, 16, 20, 21, 25, 26, 30, 31, 35, 36, 40, 41, 45, 46, 50, 51, 55, 56)

# WebSocket Configuration
WS_MIN_RECONNECT_DELAY: Final = 5  # seconds
WS_MAX_RECONNECT_DELAY: Final = 60  # seconds
WS_HEARTBEAT_INTERVAL: Final = 30  # seconds

# Amber API rate limits
API_RATE_LIMIT: Final = 50  # requests per 5 minutes

# Forecast configuration
FORECAST_INTERVALS: Final = 288  # 24 hours at 5-min resolution, or 48 hours at 30-min

# Channel types
CHANNEL_GENERAL: Final = "general"
CHANNEL_FEED_IN: Final = "feed_in"
CHANNEL_CONTROLLED_LOAD: Final = "controlled_load"

ALL_CHANNELS: Final = (CHANNEL_GENERAL, CHANNEL_FEED_IN, CHANNEL_CONTROLLED_LOAD)

# Pricing modes
PRICING_MODE_AEMO: Final = "aemo"  # Uses per_kwh
PRICING_MODE_APP: Final = "app"  # Uses advanced_price_predicted

# Price descriptors
DESCRIPTOR_EXTREMELY_LOW: Final = "extremely_low"
DESCRIPTOR_VERY_LOW: Final = "very_low"
DESCRIPTOR_LOW: Final = "low"
DESCRIPTOR_NEUTRAL: Final = "neutral"
DESCRIPTOR_HIGH: Final = "high"
DESCRIPTOR_SPIKE: Final = "spike"

# Config keys
CONF_API_TOKEN: Final = "api_token"  # noqa: S105
CONF_SITE_ID: Final = "site_id"
CONF_SITE_NAME: Final = "site_name"
CONF_PRICING_MODE: Final = "pricing_mode"
CONF_ENABLE_GENERAL: Final = "enable_general"
CONF_ENABLE_FEED_IN: Final = "enable_feed_in"
CONF_ENABLE_CONTROLLED_LOAD: Final = "enable_controlled_load"
CONF_ENABLE_WEBSOCKET: Final = "enable_websocket"
CONF_WAIT_FOR_CONFIRMED: Final = "wait_for_confirmed"

# Default options
DEFAULT_PRICING_MODE: Final = PRICING_MODE_AEMO
DEFAULT_ENABLE_GENERAL: Final = True
DEFAULT_ENABLE_FEED_IN: Final = True
DEFAULT_ENABLE_CONTROLLED_LOAD: Final = False
DEFAULT_ENABLE_WEBSOCKET: Final = True
DEFAULT_WAIT_FOR_CONFIRMED: Final = True  # Keep polling until non-estimated price

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
ATTR_CHANNEL_TYPE: Final = "channel_type"
ATTR_TARIFF_INFORMATION: Final = "tariff_information"

# Data source tracking
DATA_SOURCE_POLLING: Final = "polling"
DATA_SOURCE_WEBSOCKET: Final = "websocket"
