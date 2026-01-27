"""Data source merger for combining polling and websocket data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .const import ATTR_FORECASTS, DATA_SOURCE_POLLING, DATA_SOURCE_WEBSOCKET
from .types import ChannelData


@dataclass
class MergedResult:
    """Result of merging data sources."""

    data: dict[str, Any]
    source: str


class DataSourceMerger:
    """Manages merging of polling and websocket data sources.

    Stores current interval data and forecasts separately:
    - Current interval: updated by both polling and websocket, fresher wins
    - Forecasts: only from polling, preserved across websocket updates
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

        Args:
            data: The new polling data (may contain forecasts)

        """
        now = datetime.now(UTC)
        self._polling_current_timestamp = now

        # Separate current interval from forecasts
        for channel, channel_data in data.items():
            # Skip metadata keys
            if channel.startswith("_"):
                continue

            # Extract forecasts if present
            forecasts = channel_data.get(ATTR_FORECASTS)
            if forecasts is not None:
                self._forecasts[channel] = forecasts
                self._forecasts_timestamp = now

            # Store current interval without forecasts
            current_only: ChannelData = {
                k: v for k, v in channel_data.items() if k != ATTR_FORECASTS
            }
            self._polling_current[channel] = current_only

    def update_websocket(self, data: dict[str, ChannelData]) -> None:
        """Update websocket data.

        WebSocket only provides current interval data, never forecasts.

        Args:
            data: The new websocket data

        """
        self._websocket_current = data
        self._websocket_current_timestamp = datetime.now(UTC)

    def get_merged_data(self) -> MergedResult:
        """Merge data from polling and websocket sources.

        Uses fresher source for current interval, always attaches forecasts from polling.

        Returns:
            MergedResult containing the merged data and source name

        """
        current_data: dict[str, Any]
        data_source: str

        polling_fresh = self._polling_current_timestamp is not None
        websocket_fresh = self._websocket_current_timestamp is not None

        # Determine which source has fresher current interval data
        if (
            websocket_fresh
            and polling_fresh
            and self._websocket_current_timestamp is not None
            and self._polling_current_timestamp is not None
        ):
            if self._websocket_current_timestamp > self._polling_current_timestamp:
                current_data = {k: dict(v) for k, v in self._websocket_current.items()}
                data_source = DATA_SOURCE_WEBSOCKET
            else:
                current_data = {k: dict(v) for k, v in self._polling_current.items()}
                data_source = DATA_SOURCE_POLLING
        elif websocket_fresh:
            current_data = {k: dict(v) for k, v in self._websocket_current.items()}
            data_source = DATA_SOURCE_WEBSOCKET
        elif polling_fresh:
            current_data = {k: dict(v) for k, v in self._polling_current.items()}
            data_source = DATA_SOURCE_POLLING
        else:
            current_data = {}
            data_source = DATA_SOURCE_POLLING

        # Attach forecasts from polling to each channel
        for channel, forecasts in self._forecasts.items():
            if channel in current_data:
                current_data[channel][ATTR_FORECASTS] = forecasts
            elif forecasts:
                # Channel exists in forecasts but not in current data
                # Create channel entry with just forecasts
                current_data[channel] = {ATTR_FORECASTS: forecasts}

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
            result[channel] = dict(data)
            if channel in self._forecasts:
                result[channel][ATTR_FORECASTS] = self._forecasts[channel]
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
