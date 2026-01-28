"""Type definitions for Amber Express integration."""

from __future__ import annotations

from typing import TypedDict, TypeGuard

# =============================================================================
# WebSocket Types (camelCase, matches wire format)
# =============================================================================


class WSTariffInformation(TypedDict, total=False):
    """Tariff information from WebSocket message."""

    period: str | None
    season: str | None
    block: float | None
    demandWindow: bool | None


class WSAdvancedPrice(TypedDict, total=False):
    """Advanced price data from WebSocket message."""

    low: float
    predicted: float
    high: float


class WSPriceInterval(TypedDict, total=False):
    """Price interval from WebSocket message."""

    type: str
    date: str
    duration: int
    startTime: str
    endTime: str
    nemTime: str
    perKwh: float
    renewables: float
    spotPerKwh: float
    channelType: str
    spikeStatus: str
    tariffInformation: WSTariffInformation
    descriptor: str
    estimate: bool
    advancedPrice: WSAdvancedPrice


class WSPriceUpdate(TypedDict):
    """Price update message from WebSocket."""

    siteId: str
    prices: list[WSPriceInterval]


# =============================================================================
# Internal Data Types (snake_case, processed format)
# =============================================================================


class AdvancedPriceData(TypedDict, total=False):
    """Advanced price data in internal format."""

    low: float | None
    predicted: float | None
    high: float | None


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


class ChannelInfo(TypedDict):
    """Channel information from site info."""

    identifier: str | None
    type: str
    tariff: str | None


class SiteInfoData(TypedDict, total=False):
    """Site information data."""

    id: str
    nmi: str
    network: str
    status: str
    channels: list[ChannelInfo]
    active_from: str | None
    interval_length: float


class TariffInfoData(TypedDict, total=False):
    """Current tariff information."""

    period: str | None
    season: str | None
    block: float | None
    demand_window: bool | None


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


def is_ws_price_interval(data: object) -> TypeGuard[WSPriceInterval]:
    """Validate a price interval from WebSocket."""
    if not isinstance(data, dict):
        return False
    # Required fields for processing
    return isinstance(data.get("channelType"), str) and isinstance(data.get("perKwh"), int | float)


def is_ws_price_update(data: object) -> TypeGuard[WSPriceUpdate]:
    """Validate a price update message from WebSocket."""
    if not isinstance(data, dict):
        return False
    prices = data.get("prices")
    if not isinstance(prices, list):
        return False
    return all(is_ws_price_interval(p) for p in prices)
