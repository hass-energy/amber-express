"""Data source merger for combining polling and websocket data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .const import DATA_SOURCE_POLLING, DATA_SOURCE_WEBSOCKET
from .types import ChannelData


@dataclass
class MergedResult:
    """Result of merging data sources."""

    data: dict[str, Any]
    source: str


class DataSourceMerger:
    """Manages merging of polling and websocket data sources.

    This class tracks data from both sources and determines which is fresher
    when producing the merged result.
    """

    def __init__(self) -> None:
        """Initialize the data source merger."""
        self._polling_data: dict[str, ChannelData] = {}
        self._websocket_data: dict[str, ChannelData] = {}
        self._polling_timestamp: datetime | None = None
        self._websocket_timestamp: datetime | None = None

    def update_polling(self, data: dict[str, ChannelData]) -> None:
        """Update polling data.

        Args:
            data: The new polling data

        """
        self._polling_data = data
        self._polling_timestamp = datetime.now(UTC)

    def update_websocket(self, data: dict[str, ChannelData]) -> None:
        """Update websocket data.

        Args:
            data: The new websocket data

        """
        self._websocket_data = data
        self._websocket_timestamp = datetime.now(UTC)

    def get_merged_data(self) -> MergedResult:
        """Merge data from polling and websocket sources.

        Returns the fresher data source based on timestamps.

        Returns:
            MergedResult containing the merged data and source name

        """
        current_data: dict[str, Any]
        data_source: str

        polling_fresh = self._polling_timestamp is not None
        websocket_fresh = self._websocket_timestamp is not None

        if (
            websocket_fresh
            and polling_fresh
            and self._websocket_timestamp is not None
            and self._polling_timestamp is not None
        ):
            # Use whichever is more recent
            if self._websocket_timestamp > self._polling_timestamp:
                current_data = dict(self._websocket_data)
                data_source = DATA_SOURCE_WEBSOCKET
            else:
                current_data = dict(self._polling_data)
                data_source = DATA_SOURCE_POLLING
        elif websocket_fresh:
            current_data = dict(self._websocket_data)
            data_source = DATA_SOURCE_WEBSOCKET
        elif polling_fresh:
            current_data = dict(self._polling_data)
            data_source = DATA_SOURCE_POLLING
        else:
            current_data = {}
            data_source = DATA_SOURCE_POLLING

        # Add metadata
        current_data["_source"] = data_source
        current_data["_polling_timestamp"] = self._polling_timestamp.isoformat() if self._polling_timestamp else None
        current_data["_websocket_timestamp"] = (
            self._websocket_timestamp.isoformat() if self._websocket_timestamp else None
        )

        return MergedResult(data=current_data, source=data_source)

    @property
    def polling_data(self) -> dict[str, ChannelData]:
        """Get the current polling data."""
        return self._polling_data

    @property
    def websocket_data(self) -> dict[str, ChannelData]:
        """Get the current websocket data."""
        return self._websocket_data

    @property
    def polling_timestamp(self) -> datetime | None:
        """Get the polling timestamp."""
        return self._polling_timestamp

    @property
    def websocket_timestamp(self) -> datetime | None:
        """Get the websocket timestamp."""
        return self._websocket_timestamp
