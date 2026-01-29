"""Type definitions for Amber Express integration."""

from __future__ import annotations

from typing import TypedDict

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

    Required fields (always present when the dict has interval data):
    - per_kwh, spot_per_kwh, start_time, end_time, nem_time
    - renewables, descriptor, spike_status, estimate

    Optional fields (only present when SDK provides them):
    - advanced_price_predicted, demand_window, tariff_period, tariff_season, tariff_block
    - forecasts (only on top-level channel entries, not forecast items)

    Note: total=False allows incremental building and partial dicts (e.g., forecasts-only).
    """

    # Required fields (SDK guarantees these values when interval data exists)
    per_kwh: float
    spot_per_kwh: float
    start_time: str
    end_time: str
    nem_time: str
    renewables: float
    descriptor: str
    spike_status: str
    estimate: bool

    # Optional fields (from SDK optional fields)
    advanced_price_predicted: AdvancedPriceData
    demand_window: bool
    tariff_period: str
    tariff_season: str
    tariff_block: float
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
