"""Interval-keyed price store with a derived view of what sensors should show."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum

from custom_components.amber_express.const import (
    ATTR_DEMAND_WINDOW,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECAST,
    ATTR_NEM_TIME,
    ATTR_START_TIME,
    CHANNEL_GENERAL,
)
from custom_components.amber_express.types import ChannelData

# Attributes that describe the interval rather than its price; a held price takes these from the current interval
_INTERVAL_ATTRS = frozenset({ATTR_START_TIME, ATTR_END_TIME, ATTR_NEM_TIME, ATTR_DEMAND_WINDOW})


def interval_key(start_time: str) -> datetime:
    """Key an interval by its start time rounded to the minute (Amber starts intervals at :01)."""
    start = datetime.fromisoformat(start_time)
    return (start + timedelta(seconds=30)).replace(second=0, microsecond=0)


class Rank(IntEnum):
    """How final a record is. A record never replaces a higher-ranked one."""

    FORECAST = 0
    ESTIMATE = 1
    CONFIRMED = 2


@dataclass(frozen=True)
class IntervalRecord:
    """The best data known for one channel and interval."""

    data: ChannelData
    rank: Rank
    source: str


@dataclass(frozen=True)
class PriceView:
    """What sensors should show for one interval."""

    channels: dict[str, ChannelData]
    source: str | None


class PriceStore:
    """Records every interval Amber reports, keyed by channel and interval start."""

    def __init__(self) -> None:
        """Initialize an empty store."""
        self._records: dict[str, dict[datetime, IntervalRecord]] = {}

    def record(self, data: dict[str, ChannelData], *, source: str) -> None:
        """Record the intervals in a polling or WebSocket response."""
        for channel, channel_data in data.items():
            records = self._records.setdefault(channel, {})
            current: ChannelData = {k: v for k, v in channel_data.items() if k != ATTR_FORECAST}  # type: ignore[assignment]
            if ATTR_START_TIME in current:
                rank = Rank.ESTIMATE if current[ATTR_ESTIMATE] else Rank.CONFIRMED
                _keep_best(records, IntervalRecord(current, rank, source))
            for forecast in channel_data.get(ATTR_FORECAST, []):
                _keep_best(records, IntervalRecord(forecast, Rank.FORECAST, source))  # type: ignore[arg-type]

    def is_confirmed(self, interval_start: datetime) -> bool:
        """Whether the general channel has a confirmed price for the interval starting at interval_start."""
        record = self._records.get(CHANNEL_GENERAL, {}).get(interval_start)
        return record is not None and record.rank is Rank.CONFIRMED

    def discard_before(self, interval_start: datetime) -> None:
        """Forget intervals that start before interval_start."""
        for records in self._records.values():
            for start in [start for start in records if start < interval_start]:
                del records[start]

    def view(self, interval_start: datetime, *, publish_estimates: bool) -> PriceView:
        """Derive what sensors should show for the interval starting at interval_start."""
        shown = {
            channel: _shown_record(records, interval_start, publish_estimates=publish_estimates)
            for channel, records in self._records.items()
        }
        general = shown.get(CHANNEL_GENERAL)
        return PriceView(
            channels={
                channel: _channel_view(shown[channel], records, interval_start)
                for channel, records in self._records.items()
            },
            source=general.source if general else None,
        )


def _keep_best(records: dict[datetime, IntervalRecord], record: IntervalRecord) -> None:
    key = interval_key(record.data[ATTR_START_TIME])
    existing = records.get(key)
    if existing is None or record.rank >= existing.rank:
        records[key] = record


def _channel_view(
    shown: IntervalRecord | None, records: dict[datetime, IntervalRecord], interval_start: datetime
) -> ChannelData:
    upcoming = [records[start].data for start in sorted(records) if start > interval_start]
    if shown is None:
        return {ATTR_FORECAST: upcoming}
    return {**shown.data, ATTR_FORECAST: [shown.data, *upcoming]}


def _shown_record(
    records: dict[datetime, IntervalRecord], interval_start: datetime, *, publish_estimates: bool
) -> IntervalRecord | None:
    now = records.get(interval_start)
    if now is None:
        return None
    if now.rank is Rank.CONFIRMED or (publish_estimates and now.rank is Rank.ESTIMATE):
        return now
    earlier_prices = [start for start, r in records.items() if start < interval_start and r.rank > Rank.FORECAST]
    if not earlier_prices:
        return None
    return _held(records[max(earlier_prices)], now)


def _held(previous: IntervalRecord, now: IntervalRecord) -> IntervalRecord:
    """Hold the previous price for the current interval until the current price is publishable."""
    held = {k: v for k, v in previous.data.items() if k not in _INTERVAL_ATTRS}
    held.update({k: v for k, v in now.data.items() if k in _INTERVAL_ATTRS})
    return IntervalRecord({**held, ATTR_ESTIMATE: True}, Rank.ESTIMATE, previous.source)  # type: ignore[arg-type]
