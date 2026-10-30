"""Interval-keyed price store with a derived view of what sensors should show."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def interval_key(start_time: str) -> datetime:
    """Key an interval by its start time rounded to the minute (Amber starts intervals at :01)."""
    start = datetime.fromisoformat(start_time)
    return (start + timedelta(seconds=30)).replace(second=0, microsecond=0)


def confirms_interval(data: dict[str, ChannelData], interval_start: datetime) -> bool:
    """Whether every channel reporting a current interval has a confirmed price for the one at interval_start."""
    current = [channel_data for channel_data in data.values() if ATTR_START_TIME in channel_data]
    return bool(current) and all(
        interval_key(channel_data[ATTR_START_TIME]) == interval_start and channel_data[ATTR_ESTIMATE] is False
        for channel_data in current
    )


class Rank(IntEnum):
    """How final a record is. A record never replaces a higher-ranked one."""

    FORECAST = 0
    ESTIMATE = 1
    CONFIRMED = 2


@dataclass(frozen=True)
class HoldPolicy:
    """Hold the previous price while the current one is unconfirmed, giving up after timeout (never when None)."""

    timeout: timedelta | None


@dataclass(frozen=True)
class IntervalRecord:
    """The best data known for one channel and interval."""

    data: ChannelData
    rank: Rank
    source: str


@dataclass(frozen=True)
class PriceView:
    """What sensors should show during one interval."""

    interval_start: datetime
    channels: dict[str, ChannelData]
    source: str | None


class PriceStore:
    """Records every interval Amber reports, keyed by channel and interval start."""

    def __init__(self, interval_length: timedelta, *, hold: HoldPolicy | None) -> None:
        """Initialize an empty store for a site with the given interval length."""
        self._interval_length = interval_length
        self._hold = hold
        self._records: dict[str, dict[datetime, IntervalRecord]] = {}

    def record(self, data: dict[str, ChannelData], source: str) -> None:
        """Record the intervals in a polling or WebSocket response."""
        for channel, channel_data in data.items():
            records = self._records.setdefault(channel, {})
            current = channel_data.copy()
            current.pop(ATTR_FORECAST, None)
            if ATTR_START_TIME in current:
                rank = Rank.ESTIMATE if current[ATTR_ESTIMATE] else Rank.CONFIRMED
                _keep_best(records, IntervalRecord(current, rank, source))
            for forecast in channel_data.get(ATTR_FORECAST, []):
                _keep_best(records, IntervalRecord(forecast, Rank.FORECAST, source))

    def discard_before(self, interval_start: datetime) -> None:
        """Forget intervals that start before interval_start."""
        for records in self._records.values():
            for start in [start for start in records if start < interval_start]:
                del records[start]

    def interval_start(self, now: datetime) -> datetime:
        """Start of the interval containing now."""
        return _EPOCH + (now - _EPOCH) // self._interval_length * self._interval_length

    def view(self, now: datetime) -> PriceView:
        """Derive what sensors should show at the given time."""
        interval_start = self.interval_start(now)
        elapsed = now - interval_start
        shown = {channel: self._shown(records, interval_start, elapsed) for channel, records in self._records.items()}
        general = shown.get(CHANNEL_GENERAL)
        return PriceView(
            interval_start=interval_start,
            channels={
                channel: _channel_view(shown[channel], records, interval_start)
                for channel, records in self._records.items()
            },
            source=general.source if general else None,
        )

    def _publishes_estimates(self, elapsed: timedelta) -> bool:
        return self._hold is None or (self._hold.timeout is not None and elapsed >= self._hold.timeout)

    def _shown(
        self, records: dict[datetime, IntervalRecord], interval_start: datetime, elapsed: timedelta
    ) -> IntervalRecord | None:
        current = records.get(interval_start)
        if current is None:
            return None
        if current.rank is Rank.CONFIRMED or self._publishes_estimates(elapsed):
            return current
        previous_start = interval_start - self._interval_length
        previous_final = self._shown(records, previous_start, self._interval_length)
        if previous_final is None:
            return None
        return _held(previous_final, current)


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


def _held(previous: IntervalRecord, current: IntervalRecord) -> IntervalRecord:
    """Show the previous interval's final price with the current interval's timing."""
    held = previous.data.copy()
    held.pop(ATTR_DEMAND_WINDOW, None)
    held[ATTR_START_TIME] = current.data[ATTR_START_TIME]
    held[ATTR_END_TIME] = current.data[ATTR_END_TIME]
    held[ATTR_NEM_TIME] = current.data[ATTR_NEM_TIME]
    if ATTR_DEMAND_WINDOW in current.data:
        held[ATTR_DEMAND_WINDOW] = current.data[ATTR_DEMAND_WINDOW]
    held[ATTR_ESTIMATE] = True
    return IntervalRecord(held, Rank.ESTIMATE, previous.source)
