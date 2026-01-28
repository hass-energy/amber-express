"""Type definitions for Amber Express integration."""

from __future__ import annotations

from typing import TypedDict, TypeGuard

# =============================================================================
# WebSocket Types (minimal wrapper for message envelope)
# =============================================================================


class WSPriceUpdate(TypedDict):
    """Price update message from WebSocket.

    The prices list contains CurrentInterval-compatible dicts that are
    parsed into SDK CurrentInterval objects using CurrentInterval.from_dict().
    """

    siteId: str
    prices: list[dict]


# =============================================================================
# Internal Data Types (snake_case, processed format)
# =============================================================================


class AdvancedPriceData(TypedDict, total=False):
    """Advanced price data in internal format.

    All fields are required floats when the dict is present - the SDK's
    AdvancedPrice model requires all fields, so they're guaranteed when available.
    """

    low: float
    predicted: float
    high: float


class ChannelData(TypedDict, total=False):
    """Per-channel price data in internal format.

    Also used for forecast entries - each forecast contains the same
    fields as a current interval (except nested forecasts).
    """

    per_kwh: float | None
    spot_per_kwh: float | None
    start_time: str | None
    end_time: str | None
    nem_time: str | None
    renewables: float | None
    descriptor: str | None
    spike_status: str | None
    estimate: bool | None
    advanced_price_predicted: AdvancedPriceData
    demand_window: bool | None
    tariff_period: str | None
    tariff_season: str | None
    tariff_block: float | None
    # Forecasts are ChannelData without nested forecasts
    forecasts: list[dict]


class RateLimitInfo(TypedDict):
    """Rate limit information from API response headers (IETF RateLimit headers).

    See: https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/
    """

    limit: int  # Maximum requests in window (from ratelimit-limit)
    remaining: int  # Requests remaining in current window
    reset_seconds: int  # Seconds until quota resets
    window_seconds: int  # Window size in seconds (from policy)
    policy: str  # Raw policy string (e.g., "50;w=300")


class CoordinatorData(TypedDict, total=False):
    """Data structure returned by the coordinator."""

    general: ChannelData
    feed_in: ChannelData
    controlled_load: ChannelData
    _source: str
    _polling_timestamp: str | None
    _websocket_timestamp: str | None


# =============================================================================
# TypeGuards for WebSocket Validation
# =============================================================================


def is_ws_price_update(data: object) -> TypeGuard[WSPriceUpdate]:
    """Validate a price update message from WebSocket.

    Checks the envelope structure. Individual prices are validated when
    parsing via CurrentInterval.from_dict().
    """
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("siteId"), str):
        return False
    prices = data.get("prices")
    if not isinstance(prices, list):
        return False
    # Basic validation - each price must be a dict with required fields
    return all(
        isinstance(p, dict) and isinstance(p.get("channelType"), str) and isinstance(p.get("perKwh"), int | float)
        for p in prices
    )
