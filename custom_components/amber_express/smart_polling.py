"""Smart polling manager for optimized API polling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging

from .cdf_polling import CDFPollingStats, CDFPollingStrategy, IntervalObservation
from .types import RateLimitInfo

_LOGGER = logging.getLogger(__name__)


@dataclass
class PollingState:
    """Current state of the polling manager."""

    current_interval_start: datetime | None
    has_confirmed_price: bool
    forecasts_pending: bool
    poll_count_this_interval: int
    first_interval_after_startup: bool
    last_estimate_elapsed: float | None


class SmartPollingManager:
    """Manages smart polling decisions based on interval timing and confirmation status.

    This class encapsulates the logic for determining when to poll the Amber API,
    optimizing for minimal API calls while ensuring timely price updates.
    """

    def __init__(
        self, observations: list[IntervalObservation] | None = None
    ) -> None:
        """Initialize the polling manager.

        Args:
            observations: Optional pre-loaded observations from storage

        """
        self._current_interval_start: datetime | None = None
        self._has_confirmed_price = False
        self._poll_count_this_interval = 0
        self._first_interval_after_startup = True
        self._last_estimate_elapsed: float | None = None
        self._forecasts_pending = False
        self._cdf_strategy = CDFPollingStrategy(observations)

    def _get_current_5min_interval(self) -> datetime:
        """Get the start of the current 5-minute interval."""
        now = datetime.now(UTC)
        # Round down to nearest 5 minutes
        minutes = (now.minute // 5) * 5
        return now.replace(minute=minutes, second=0, microsecond=0)

    def _calculate_polls_per_interval(self, rate_limit_info: RateLimitInfo) -> int | None:
        """Calculate polls per interval based on rate limit quota.

        Args:
            rate_limit_info: Current rate limit information from API

        Returns:
            Number of confirmatory polls (equals remaining quota), or None if unavailable

        """
        remaining = rate_limit_info.get("remaining")
        if remaining is None:
            return None
        return remaining

    def should_poll(
        self,
        *,
        has_data: bool,
        rate_limit_until: datetime | None = None,
        rate_limit_info: RateLimitInfo | None = None,
    ) -> bool:
        """Determine if we should poll using smart CDF-based polling.

        Args:
            has_data: Whether we have any existing data (for first-run detection)
            rate_limit_until: When rate limit expires (None if not limited)
            rate_limit_info: Current rate limit quota info (for calculating k)

        Returns:
            True if we should poll now, False otherwise

        """
        current_interval = self._get_current_5min_interval()
        now = datetime.now(UTC)

        # Reset state if we've moved to a new interval (or first run)
        if self._current_interval_start != current_interval:
            is_first_run = not has_data
            self._current_interval_start = current_interval
            self._has_confirmed_price = False
            self._forecasts_pending = False
            self._poll_count_this_interval = 0
            self._last_estimate_elapsed = None

            # Calculate optimal k from rate limit info
            polls_per_interval = None
            if rate_limit_info:
                polls_per_interval = self._calculate_polls_per_interval(rate_limit_info)

            self._cdf_strategy.start_interval(polls_per_interval)

            if is_first_run:
                _LOGGER.debug("First poll - fetching initial data")
            else:
                # Clear the first-interval flag now that we're in a real new interval
                self._first_interval_after_startup = False
                _LOGGER.debug(
                    "New 5-minute interval started: %s (k=%d, scheduled polls: %s)",
                    current_interval,
                    len(self._cdf_strategy.scheduled_polls),
                    [f"{t:.1f}s" for t in self._cdf_strategy.scheduled_polls],
                )
            return True  # Always poll at start of new interval for estimate

        # Don't poll if we already have confirmed price (unless forecasts pending)
        if self._has_confirmed_price and not self._forecasts_pending:
            return False

        # If forecasts pending, check rate limit backoff before retrying
        if self._forecasts_pending and rate_limit_until and now < rate_limit_until:
            return False

        # If forecasts pending but not rate limited, allow retry
        if self._forecasts_pending:
            return True

        # Use CDF strategy for confirmatory polling
        if self._current_interval_start is None:
            # Should never happen - _current_interval_start is set when interval changes
            return True
        elapsed = (now - self._current_interval_start).total_seconds()
        return self._cdf_strategy.should_poll_for_confirmed(elapsed)

    def on_poll_started(self) -> None:
        """Record that a poll has started."""
        self._poll_count_this_interval += 1

        # Track confirmatory polls (polls after the first estimate poll)
        if self._poll_count_this_interval > 1:
            self._cdf_strategy.increment_confirmatory_poll()

    def on_estimate_received(self) -> None:
        """Record that an estimated price was received."""
        if self._current_interval_start is not None:
            now = datetime.now(UTC)
            self._last_estimate_elapsed = (now - self._current_interval_start).total_seconds()

    def on_confirmed_received(self) -> None:
        """Record that a confirmed price was received and record observation."""
        self._has_confirmed_price = True

        # Record observation (skip first interval after startup if no estimate seen)
        if self._current_interval_start is not None and not self._first_interval_after_startup:
            now = datetime.now(UTC)
            confirmed_elapsed = (now - self._current_interval_start).total_seconds()

            if self._last_estimate_elapsed is not None:
                self._cdf_strategy.record_observation(
                    start=self._last_estimate_elapsed,
                    end=confirmed_elapsed,
                )
                _LOGGER.debug(
                    "Recorded observation [%.1fs, %.1fs], next polls: %s",
                    self._last_estimate_elapsed,
                    confirmed_elapsed,
                    [f"{t:.1f}s" for t in self._cdf_strategy.scheduled_polls],
                )
            else:
                _LOGGER.debug(
                    "Confirmed at %.1fs but no estimate seen, skipping observation",
                    confirmed_elapsed,
                )
        elif self._first_interval_after_startup:
            _LOGGER.debug("Skipping observation on first interval after startup")

    def set_forecasts_pending(self) -> None:
        """Mark forecasts as pending retry."""
        self._forecasts_pending = True

    def clear_forecasts_pending(self) -> None:
        """Clear forecasts pending flag."""
        self._forecasts_pending = False

    @property
    def has_confirmed_price(self) -> bool:
        """Return whether we have a confirmed price for this interval."""
        return self._has_confirmed_price

    @property
    def forecasts_pending(self) -> bool:
        """Return whether forecasts are pending retry."""
        return self._forecasts_pending

    @property
    def poll_count_this_interval(self) -> int:
        """Return the number of polls this interval."""
        return self._poll_count_this_interval

    @property
    def first_interval_after_startup(self) -> bool:
        """Return whether this is the first interval after startup."""
        return self._first_interval_after_startup

    def get_cdf_stats(self) -> CDFPollingStats:
        """Get CDF polling statistics for diagnostics."""
        return self._cdf_strategy.get_stats()

    @property
    def observations(self) -> list[IntervalObservation]:
        """Get current observations for persistence."""
        return self._cdf_strategy.observations

    def get_state(self) -> PollingState:
        """Get current polling state for testing/debugging."""
        return PollingState(
            current_interval_start=self._current_interval_start,
            has_confirmed_price=self._has_confirmed_price,
            forecasts_pending=self._forecasts_pending,
            poll_count_this_interval=self._poll_count_this_interval,
            first_interval_after_startup=self._first_interval_after_startup,
            last_estimate_elapsed=self._last_estimate_elapsed,
        )
