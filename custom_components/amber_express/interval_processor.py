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
    """Transforms Amber API interval responses into internal data structures."""

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

            # Get channel type from the actual interval
            if not hasattr(actual, "channel_type"):
                _LOGGER.debug("Interval missing channel_type: %s", type(actual).__name__)
                continue

            channel_type_raw = (
                actual.channel_type.value if hasattr(actual.channel_type, "value") else str(actual.channel_type)
            )
            channel = CHANNEL_TYPE_MAP.get(channel_type_raw, channel_type_raw)

            if channel not in forecast_intervals:
                forecast_intervals[channel] = []

            # Determine interval type
            # CurrentInterval = the current price (check estimate field for confirmed status)
            # ActualInterval = historical confirmed prices (past intervals, not current)
            # ForecastInterval = future prediction
            if isinstance(actual, CurrentInterval):
                # CurrentInterval is the current price - always use it
                current_intervals[channel] = actual
            elif isinstance(actual, ForecastInterval):
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
        if self._pricing_mode == PRICING_MODE_APP:
            # Use advanced_price.predicted if available
            price_cents = None
            if hasattr(interval, "advanced_price") and interval.advanced_price:
                price_cents = getattr(interval.advanced_price, "predicted", None)
            if price_cents is None:
                price_cents = interval.per_kwh
        else:
            # Use per_kwh (AEMO-based)
            price_cents = interval.per_kwh

        price = cents_to_dollars(price_cents)
        spot_per_kwh = cents_to_dollars(getattr(interval, "spot_per_kwh", None))

        # Extract descriptor
        descriptor = None
        if hasattr(interval, "descriptor"):
            descriptor = (
                interval.descriptor.value if hasattr(interval.descriptor, "value") else str(interval.descriptor)
            )

        # Extract spike status
        spike_status = None
        if hasattr(interval, "spike_status"):
            spike_status = (
                interval.spike_status.value if hasattr(interval.spike_status, "value") else str(interval.spike_status)
            )

        # Determine estimate status based on interval type
        # ForecastInterval is always estimated, CurrentInterval has an estimate field
        is_estimate = True if isinstance(interval, ForecastInterval) else getattr(interval, "estimate", True)

        data: ChannelData = {
            ATTR_PER_KWH: price,
            ATTR_SPOT_PER_KWH: spot_per_kwh,
            ATTR_START_TIME: interval.start_time.isoformat() if interval.start_time else None,
            ATTR_END_TIME: interval.end_time.isoformat() if interval.end_time else None,
            ATTR_NEM_TIME: getattr(interval, "nem_time", None),
            ATTR_RENEWABLES: getattr(interval, "renewables", None),
            ATTR_DESCRIPTOR: descriptor,
            ATTR_SPIKE_STATUS: spike_status,
            ATTR_ESTIMATE: is_estimate,
        }

        # Add advanced price data if available
        if hasattr(interval, "advanced_price") and interval.advanced_price:
            advanced_price_data: AdvancedPriceData = {
                "low": cents_to_dollars(getattr(interval.advanced_price, "low", None)),
                "predicted": cents_to_dollars(getattr(interval.advanced_price, "predicted", None)),
                "high": cents_to_dollars(getattr(interval.advanced_price, "high", None)),
            }
            data[ATTR_ADVANCED_PRICE] = advanced_price_data

        # Add tariff information if available
        if hasattr(interval, "tariff_information") and interval.tariff_information:
            tariff = interval.tariff_information
            data[ATTR_DEMAND_WINDOW] = getattr(tariff, "demand_window", None)
            data[ATTR_TARIFF_PERIOD] = getattr(tariff, "period", None)
            data[ATTR_TARIFF_SEASON] = getattr(tariff, "season", None)
            data[ATTR_TARIFF_BLOCK] = getattr(tariff, "block", None)

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
