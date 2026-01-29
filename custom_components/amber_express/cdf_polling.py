"""CDF-based polling strategy for optimal confirmatory poll timing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .cdf_algorithm import IntervalObservation, build_cdf, compute_blend_weight, compute_poll_times
from .cdf_cold_start import COLD_START_OBSERVATIONS

# Re-export for backwards compatibility
__all__ = ["CDFPollingStats", "CDFPollingStrategy", "IntervalObservation"]


@dataclass
class CDFPollingStats:
    """Diagnostic statistics for CDF polling strategy."""

    observation_count: int
    scheduled_polls: list[float]
    next_poll_index: int
    confirmatory_poll_count: int
    polls_per_interval: int
    last_observation: IntervalObservation | None


class CDFPollingStrategy:
    """Stateful wrapper that manages observations and polling state.

    Responsibilities:
    - Maintaining a rolling window of interval observations
    - Caching the CDF to avoid recomputation
    - Tracking scheduled polls and which have been executed
    - Providing a simple interface for the coordinator

    The actual CDF algorithm is implemented in cdf_algorithm.py as pure functions.

    Cold start: Uses real observations from historical data until real-time
    data is collected.
    """

    # Configuration constants
    WINDOW_SIZE = 100  # Rolling window of observations (N)

    # Uniform blending thresholds as fractions of quota
    UNIFORM_BLEND_FRACTION_HIGH = 0.3  # Pure targeted CDF when k >= quota * this
    UNIFORM_BLEND_FRACTION_LOW = 0.2  # Pure uniform distribution when k <= quota * this

    def __init__(
        self,
        observations: list[IntervalObservation] | None = None,
    ) -> None:
        """Initialize the strategy.

        Args:
            observations: Optional pre-loaded observations from storage

        """
        if observations is not None:
            self._observations = observations[-self.WINDOW_SIZE :]
        else:
            # Cold start: use real historical observations
            self._observations = list(COLD_START_OBSERVATIONS)

        self._scheduled_polls: list[float] = []
        self._next_poll_index = 0
        self._confirmatory_poll_count = 0
        self._polls_per_interval = 0
        self._quota: int | None = None

        # Cached CDF arrays (computed lazily)
        self._cdf_times: NDArray[np.float64] | None = None
        self._cdf_probs: NDArray[np.float64] | None = None

    def start_interval(self, polls_per_interval: int | None = None) -> None:
        """Reset state for a new interval.

        Args:
            polls_per_interval: Number of confirmatory polls to schedule.
                If None, uses the previous value (or default on first call).

        """
        self._next_poll_index = 0
        self._confirmatory_poll_count = 0

        # Update polls per interval if provided
        if polls_per_interval is not None:
            self._polls_per_interval = polls_per_interval
            # Recompute schedule with new k
            self._recompute_schedule()

    def update_budget(
        self,
        polls_per_interval: int,
        elapsed_seconds: float,
        reset_seconds: int,
        quota: int,
    ) -> None:
        """Update the poll budget mid-interval based on new rate limit info.

        Recomputes the schedule using conditional probability - since we know
        the event hasn't occurred by elapsed_seconds, we sample from P(T | T > t).

        When poll budget is low, blends targeted poll times with uniform distribution
        to spread remaining polls evenly until the rate limit resets.

        Args:
            polls_per_interval: New number of confirmatory polls (from remaining quota)
            elapsed_seconds: Current elapsed time in the interval
            reset_seconds: Seconds until rate limit quota resets
            quota: Rate limit quota (limit). Used to compute blend thresholds.

        """
        self._polls_per_interval = polls_per_interval
        self._quota = quota
        self._recompute_schedule(
            condition_on_elapsed=elapsed_seconds,
            reset_seconds=reset_seconds,
        )
        # All scheduled polls are in the future, start from index 0
        self._next_poll_index = 0

    def record_observation(self, start: float, end: float) -> None:
        """Record a new interval observation and update the CDF.

        Args:
            start: Seconds from interval start when last estimate was received
            end: Seconds from interval start when confirmed was received

        """
        # Ensure valid interval (start < end)
        if start >= end:
            return

        observation: IntervalObservation = {"start": start, "end": end}
        self._observations.append(observation)

        # Maintain rolling window
        if len(self._observations) > self.WINDOW_SIZE:
            self._observations = self._observations[-self.WINDOW_SIZE :]

        # Invalidate cached CDF
        self._cdf_times = None
        self._cdf_probs = None

        # Recompute poll schedule for future intervals
        self._recompute_schedule()

    def should_poll_for_confirmed(self, elapsed_seconds: float) -> bool:
        """Check if we should poll for confirmed price given elapsed time.

        Args:
            elapsed_seconds: Seconds since the interval started

        Returns:
            True if we should poll now, False otherwise

        """
        if self._next_poll_index >= len(self._scheduled_polls):
            return False

        next_poll_time = self._scheduled_polls[self._next_poll_index]
        return elapsed_seconds >= next_poll_time

    def get_next_poll_delay(self, elapsed_seconds: float) -> float | None:
        """Get the delay in seconds until the next scheduled poll.

        Args:
            elapsed_seconds: Seconds since the interval started

        Returns:
            Seconds until next poll, or None if no more polls scheduled

        """
        if self._next_poll_index >= len(self._scheduled_polls):
            return None

        next_poll_time = self._scheduled_polls[self._next_poll_index]
        delay = next_poll_time - elapsed_seconds

        # If delay is negative or very small, next poll is now
        if delay <= 0:
            return 0.0

        return delay

    def increment_confirmatory_poll(self) -> None:
        """Track that we made a confirmatory poll attempt."""
        self._confirmatory_poll_count += 1
        # Advance to next scheduled poll
        if self._next_poll_index < len(self._scheduled_polls):
            self._next_poll_index += 1

    @property
    def confirmatory_poll_count(self) -> int:
        """Get the number of confirmatory polls made this interval."""
        return self._confirmatory_poll_count

    @property
    def scheduled_polls(self) -> list[float]:
        """Get the currently scheduled poll times."""
        return self._scheduled_polls.copy()

    @property
    def observations(self) -> list[IntervalObservation]:
        """Get the current observations (for persistence)."""
        return self._observations.copy()

    def get_stats(self) -> CDFPollingStats:
        """Get diagnostic statistics."""
        return CDFPollingStats(
            observation_count=len(self._observations),
            scheduled_polls=self._scheduled_polls.copy(),
            next_poll_index=self._next_poll_index,
            confirmatory_poll_count=self._confirmatory_poll_count,
            polls_per_interval=self._polls_per_interval,
            last_observation=self._observations[-1] if self._observations else None,
        )

    def _build_cdf(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Build CDF from observations, using cache if available."""
        if self._cdf_times is not None and self._cdf_probs is not None:
            return self._cdf_times, self._cdf_probs

        cdf_times, cdf_probs = build_cdf(self._observations)

        # Cache the result
        self._cdf_times = cdf_times
        self._cdf_probs = cdf_probs

        return cdf_times, cdf_probs

    def _recompute_schedule(
        self,
        condition_on_elapsed: float | None = None,
        reset_seconds: int | None = None,
    ) -> None:
        """Recompute poll schedule using pure algorithm functions."""
        if not self._observations:
            self._scheduled_polls = []
            return

        cdf_times, cdf_probs = self._build_cdf()

        if len(cdf_times) == 0:
            self._scheduled_polls = []
            return

        blend_weight = compute_blend_weight(
            self._polls_per_interval,
            self._quota,
            fraction_high=self.UNIFORM_BLEND_FRACTION_HIGH,
            fraction_low=self.UNIFORM_BLEND_FRACTION_LOW,
        )

        self._scheduled_polls = compute_poll_times(
            cdf_times,
            cdf_probs,
            self._polls_per_interval,
            condition_on_elapsed=condition_on_elapsed,
            reset_seconds=reset_seconds,
            blend_weight=blend_weight,
        )
