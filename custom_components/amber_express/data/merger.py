"""Data source merger for combining polling and websocket data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from custom_components.amber_express.const import (
    ATTR_FORECAST,
    ATTR_START_TIME,
    DATA_SOURCE_POLLING,
    DATA_SOURCE_WEBSOCKET,
)
from custom_components.amber_express.types import ChannelData


@dataclass
class MergedResult:
    """Result of merging data sources."""

    data: dict[str, Any]
    source: str


def _extract_data_time(data: dict[str, ChannelData]) -> datetime | None:
    """Extract the interval start_time from channel data.

    Looks at the first non-metadata channel and parses its start_time ISO string.
    Returns None if no channel has a start_time.
    """
    for channel, channel_data in data.items():
        if channel.startswith("_"):
            continue
        start_time = channel_data.get(ATTR_START_TIME)
        if isinstance(start_time, str):
            return datetime.fromisoformat(start_time)
    return None


class DataSourceMerger:
    """Merges price data from polling and websocket sources with interval-based priority.

    Responsibilities:
    - Storing current interval data from polling and websocket separately
    - Storing forecasts (only available from polling API, not websocket)
    - Determining which source has fresher data based on interval start_time
    - Merging current interval with forecasts into a unified result
    - Tracking metadata about data freshness and source

    Merge strategy:
    - Current interval: compared by data start_time, not wall-clock receipt time.
      WebSocket only wins if its data covers a strictly newer interval than polling.
      For the same interval, polling wins (it has confirmed prices and forecasts).
    - Forecasts: always from polling, preserved even when websocket updates current
    """

    def __init__(self) -> None:
        """Initialize the data source merger."""
        # Current interval data (without forecasts)
        self._polling_current: dict[str, ChannelData] = {}
        self._websocket_current: dict[str, ChannelData] = {}
        self._polling_current_timestamp: datetime | None = None
        self._websocket_current_timestamp: datetime | None = None

        # Forecasts (only from polling)
        self._forecasts: dict[str, list[dict[str, Any]]] = {}
        self._forecasts_timestamp: datetime | None = None

    def update_polling(self, data: dict[str, ChannelData]) -> None:
        """Update polling data.

        Extracts current interval data and forecasts, storing them separately.
        Timestamp is derived from the data's start_time, not wall clock.

        Args:
            data: The new polling data (may contain forecasts)

        """
        data_time = _extract_data_time(data)
        if data_time is not None:
            self._polling_current_timestamp = data_time

        # Separate current interval from forecasts
        for channel, channel_data in data.items():
            # Skip metadata keys
            if channel.startswith("_"):
                continue

            # Extract forecasts if present
            forecasts = channel_data.get(ATTR_FORECAST)
            if forecasts is not None:
                self._forecasts[channel] = forecasts
                if data_time is not None:
                    self._forecasts_timestamp = data_time

            # Store current interval without forecasts
            current_only = cast("ChannelData", {k: v for k, v in channel_data.items() if k != ATTR_FORECAST})
            self._polling_current[channel] = current_only

    def update_websocket(self, data: dict[str, ChannelData]) -> None:
        """Update websocket data.

        WebSocket only provides current interval data, never forecasts.
        Timestamp is derived from the data's start_time, not wall clock.

        Args:
            data: The new websocket data

        """
        data_time = _extract_data_time(data)
        if data_time is not None:
            self._websocket_current_timestamp = data_time
        self._websocket_current = data

    def get_merged_data(self) -> MergedResult:
        """Merge data from polling and websocket sources.

        Uses fresher source for current interval, always attaches forecasts from polling.
        WebSocket only wins when it has data for a strictly newer interval (by start_time).
        Polling wins in all ambiguous cases (equal timestamps, missing timestamps).

        Returns:
            MergedResult containing the merged data and source name

        """
        current_data: dict[str, Any]
        data_source: str

        polling_has_data = bool(self._polling_current)
        websocket_has_data = bool(self._websocket_current)

        if polling_has_data and websocket_has_data:
            # Both have data - WebSocket only wins with a strictly newer interval
            if (
                self._websocket_current_timestamp is not None
                and self._polling_current_timestamp is not None
                and self._websocket_current_timestamp > self._polling_current_timestamp
            ):
                current_data = {k: dict(v) for k, v in self._websocket_current.items()}
                data_source = DATA_SOURCE_WEBSOCKET
            else:
                current_data = {k: dict(v) for k, v in self._polling_current.items()}
                data_source = DATA_SOURCE_POLLING
        elif websocket_has_data:
            current_data = {k: dict(v) for k, v in self._websocket_current.items()}
            data_source = DATA_SOURCE_WEBSOCKET
        elif polling_has_data:
            current_data = {k: dict(v) for k, v in self._polling_current.items()}
            data_source = DATA_SOURCE_POLLING
        else:
            current_data = {}
            data_source = DATA_SOURCE_POLLING

        # Attach forecasts from polling to each channel
        for channel, forecasts in self._forecasts.items():
            if channel in current_data:
                current_data[channel][ATTR_FORECAST] = forecasts
            elif forecasts:
                # Channel exists in forecasts but not in current data
                # Create channel entry with just forecasts
                current_data[channel] = {ATTR_FORECAST: forecasts}

        # Add metadata
        current_data["_source"] = data_source
        current_data["_polling_timestamp"] = (
            self._polling_current_timestamp.isoformat() if self._polling_current_timestamp else None
        )
        current_data["_websocket_timestamp"] = (
            self._websocket_current_timestamp.isoformat() if self._websocket_current_timestamp else None
        )

        return MergedResult(data=current_data, source=data_source)

    @property
    def polling_data(self) -> dict[str, ChannelData]:
        """Get the current polling data (with forecasts reattached for compatibility)."""
        result: dict[str, ChannelData] = {}
        for channel, data in self._polling_current.items():
            result[channel] = cast("ChannelData", dict(data))
            if channel in self._forecasts:
                result[channel][ATTR_FORECAST] = self._forecasts[channel]
        return result

    @property
    def websocket_data(self) -> dict[str, ChannelData]:
        """Get the current websocket data."""
        return self._websocket_current

    @property
    def polling_timestamp(self) -> datetime | None:
        """Get the polling timestamp."""
        return self._polling_current_timestamp

    @property
    def websocket_timestamp(self) -> datetime | None:
        """Get the websocket timestamp."""
        return self._websocket_current_timestamp

    @property
    def forecasts(self) -> dict[str, list[dict[str, Any]]]:
        """Get the forecasts data."""
        return self._forecasts

    @property
    def forecasts_timestamp(self) -> datetime | None:
        """Get the forecasts timestamp."""
        return self._forecasts_timestamp
