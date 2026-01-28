"""Interval processor for transforming Amber API responses."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

from amberelectric.models import CurrentInterval, ForecastInterval, Interval

from .const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DESCRIPTOR,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_NEM_TIME,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_SPOT_PER_KWH,
    ATTR_START_TIME,
    ATTR_TARIFF_BLOCK,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    PRICING_MODE_APP,
)
from .types import AdvancedPriceData, ChannelData
from .utils import cents_to_dollars

_LOGGER = logging.getLogger(__name__)

# Map Amber channel types to our constants
CHANNEL_TYPE_MAP = {
    "general": CHANNEL_GENERAL,
    "feedIn": CHANNEL_FEED_IN,
    "controlledLoad": CHANNEL_CONTROLLED_LOAD,
}


class IntervalProcessor:
    """Transforms Amber API interval responses into internal ChannelData structures.

    Responsibilities:
    - Converting Amber SDK Interval objects to internal ChannelData TypedDicts
    - Separating current intervals from forecast intervals by type
    - Applying pricing mode logic (AEMO per_kwh vs App advanced_price.predicted)
    - Converting prices from cents to dollars
    - Extracting tariff information, spike status, renewables, and other metadata
    - Building forecast lists with current interval prepended

    This class handles the impedance mismatch between the Amber SDK's object model
    and our internal snake_case TypedDict format. It's used by the coordinator for
    polling data. WebSocket data uses a separate extraction path due to different
    wire format (camelCase JSON vs SDK objects).
    """

    def __init__(self, pricing_mode: str) -> None:
        """Initialize the processor with pricing mode."""
        self._pricing_mode = pricing_mode

    def process_intervals(self, intervals: list[Interval]) -> dict[str, ChannelData]:
        """Process interval data from the API.

        Args:
            intervals: List of Interval objects from Amber API

        Returns:
            Dictionary mapping channel names to their processed data

        """
        data: dict[str, ChannelData] = {}

        # Separate intervals by type and channel
        current_intervals: dict[str, CurrentInterval] = {}
        forecast_intervals: dict[str, list[ForecastInterval]] = {}

        for interval in intervals:
            # Unwrap Interval wrapper (API returns Interval objects with actual_instance)
            actual = interval.actual_instance
            if actual is None:
                continue

            # Determine interval type and extract channel
            # CurrentInterval = the current price (check estimate field for confirmed status)
            # ActualInterval = historical confirmed prices (past intervals, not current)
            # ForecastInterval = future prediction
            if isinstance(actual, CurrentInterval):
                channel_type: str = actual.channel_type.value
                channel = CHANNEL_TYPE_MAP.get(channel_type, channel_type)
                if channel not in forecast_intervals:
                    forecast_intervals[channel] = []
                current_intervals[channel] = actual
            elif isinstance(actual, ForecastInterval):
                channel_type = actual.channel_type.value
                channel = CHANNEL_TYPE_MAP.get(channel_type, channel_type)
                if channel not in forecast_intervals:
                    forecast_intervals[channel] = []
                forecast_intervals[channel].append(actual)
            # Note: ActualInterval is historical data and not used for current price

        # Process current intervals
        for channel, interval in current_intervals.items():
            channel_data = self._extract_interval_data(interval)
            # Build forecasts with current interval prepended
            forecasts = self._build_forecasts(forecast_intervals.get(channel, []))
            # Use extracted channel_data (without forecasts) as the first forecast entry
            current_as_forecast: dict[str, Any] = {k: v for k, v in channel_data.items() if k != ATTR_FORECASTS}
            # Cast forecasts list to list[dict] for TypedDict compatibility
            channel_data[ATTR_FORECASTS] = [current_as_forecast, *forecasts]  # type: ignore[typeddict-item]
            data[channel] = channel_data

        # If we have forecasts but no current interval for a channel, still include forecasts
        for channel, fcast_list in forecast_intervals.items():
            if channel not in data and fcast_list:
                data[channel] = {  # type: ignore[typeddict-item]
                    ATTR_FORECASTS: self._build_forecasts(fcast_list),
                }

        return data

    def _extract_interval_data(self, interval: CurrentInterval | ForecastInterval) -> ChannelData:
        """Extract data from an interval object."""
        # Get the price based on pricing mode (API returns cents, we convert to dollars)
        if self._pricing_mode == PRICING_MODE_APP and interval.advanced_price:
            # Use advanced_price.predicted if available
            price_cents = interval.advanced_price.predicted
        else:
            # Use per_kwh (AEMO-based)
            price_cents = interval.per_kwh

        # Determine estimate status based on interval type
        # ForecastInterval is always estimated, CurrentInterval has an estimate field
        is_estimate = True if isinstance(interval, ForecastInterval) else interval.estimate

        data: ChannelData = {
            ATTR_PER_KWH: cents_to_dollars(price_cents),
            ATTR_SPOT_PER_KWH: cents_to_dollars(interval.spot_per_kwh),
            ATTR_START_TIME: interval.start_time.isoformat(),
            ATTR_END_TIME: interval.end_time.isoformat(),
            ATTR_NEM_TIME: interval.nem_time.isoformat() if interval.nem_time else None,
            ATTR_RENEWABLES: interval.renewables,
            ATTR_DESCRIPTOR: interval.descriptor.value,
            ATTR_SPIKE_STATUS: interval.spike_status.value,
            ATTR_ESTIMATE: is_estimate,
        }

        # Add advanced price data if available (SDK guarantees all fields are floats when present)
        if interval.advanced_price:
            ap = interval.advanced_price
            advanced_price_data: AdvancedPriceData = {
                "low": cents_to_dollars(ap.low),  # type: ignore[typeddict-item]
                "predicted": cents_to_dollars(ap.predicted),  # type: ignore[typeddict-item]
                "high": cents_to_dollars(ap.high),  # type: ignore[typeddict-item]
            }
            data[ATTR_ADVANCED_PRICE] = advanced_price_data

        # Add tariff information if available (optional field)
        if interval.tariff_information:
            tariff = interval.tariff_information
            data[ATTR_DEMAND_WINDOW] = tariff.demand_window
            data[ATTR_TARIFF_PERIOD] = tariff.period
            data[ATTR_TARIFF_SEASON] = tariff.season
            data[ATTR_TARIFF_BLOCK] = tariff.block

        return data

    def _build_forecasts(self, forecast_intervals: list[ForecastInterval]) -> list[ChannelData]:
        """Build forecast list for sensors using full interval data."""
        # Sort by start time
        sorted_intervals = sorted(
            forecast_intervals,
            key=lambda x: x.start_time if x.start_time else datetime.min.replace(tzinfo=UTC),
        )

        # Reuse _extract_interval_data to get all fields for each forecast
        return [self._extract_interval_data(interval) for interval in sorted_intervals]
