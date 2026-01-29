"""CDF-based polling strategy for optimal confirmatory poll timing."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

import numpy as np
from numpy.typing import NDArray

from .cdf_algorithm import IntervalObservation, build_cdf, sample_quantiles
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
    MIN_SAMPLE_INTERVAL = 30  # Minimum seconds between uniform samples

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

        # Cached CDF arrays (computed lazily)
        self._cdf_times: NDArray[np.float64] | None = None
        self._cdf_probs: NDArray[np.float64] | None = None

    def reset_for_new_interval(self) -> None:
        """Reset state for a new interval (no schedule computation)."""
        self._next_poll_index = 0
        self._confirmatory_poll_count = 0

    def update_budget(
        self,
        polls_per_interval: int,
        elapsed_seconds: float,
        reset_seconds: int,
        interval_seconds: int,
    ) -> None:
        """Update the poll budget mid-interval based on new rate limit info.

        Recomputes the schedule using conditional probability - since we know
        the event hasn't occurred by elapsed_seconds, we sample from P(T | T > t).

        Blends targeted poll times with uniform distribution based on minimum
        sample rate requirements.

        Args:
            polls_per_interval: New number of confirmatory polls (from remaining quota)
            elapsed_seconds: Current elapsed time in the interval
            reset_seconds: Seconds until rate limit quota resets
            interval_seconds: Length of the interval in seconds

        """
        self._polls_per_interval = polls_per_interval
        self._recompute_schedule(
            condition_on_elapsed=elapsed_seconds,
            reset_seconds=reset_seconds,
            interval_seconds=interval_seconds,
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
        interval_seconds: int | None = None,
    ) -> None:
        """Recompute poll schedule using pure algorithm functions.

        Always blends targeted CDF with uniform distribution when reset_seconds
        is available. Weights are based on a minimum sample rate target.

        Injects forced polls at boundary times (reserving budget for them):
        - Next interval start (interval_seconds)
        - Rate limit reset time (elapsed + reset_seconds)
        """
        elapsed = condition_on_elapsed or 0.0

        # Calculate forced polls first to reserve budget for them
        forced_polls: list[float] = []

        # Poll at next interval start
        if interval_seconds is not None and interval_seconds > elapsed:
            forced_polls.append(float(interval_seconds))

        # Poll at rate limit reset time
        if reset_seconds is not None and reset_seconds > 0:
            reset_time = elapsed + reset_seconds
            # Only add if it's before the next interval (otherwise interval poll covers it)
            if interval_seconds is None or reset_time < interval_seconds:
                forced_polls.append(reset_time)

        # Reserve budget for forced polls
        cdf_budget = max(0, self._polls_per_interval - len(forced_polls))

        if not self._observations or cdf_budget == 0:
            self._scheduled_polls = []
        elif reset_seconds is not None and reset_seconds > 0:
            # Calculate polls needed for minimum sample rate
            uniform_polls_needed = ceil(reset_seconds / self.MIN_SAMPLE_INTERVAL)
            uniform_end = elapsed + reset_seconds

            if cdf_budget <= uniform_polls_needed:
                # Pure uniform - not enough budget for targeted sampling
                cdf_times, cdf_probs = build_cdf([{"start": elapsed, "end": uniform_end}])
            else:
                # Blend: weight uniform based on reserved polls for minimum sample rate
                total_obs_weight = len(self._observations)
                # Scale so uniform represents uniform_polls_needed / k of total mass
                uniform_weight = total_obs_weight * uniform_polls_needed / (cdf_budget - uniform_polls_needed)
                augmented: list[IntervalObservation] = [
                    *self._observations,
                    {"start": elapsed, "end": uniform_end, "weight": uniform_weight},
                ]
                cdf_times, cdf_probs = build_cdf(augmented)

            self._scheduled_polls = sample_quantiles(
                cdf_times,
                cdf_probs,
                cdf_budget,
                condition_above=condition_on_elapsed,
            )
        else:
            cdf_times, cdf_probs = self._build_cdf()
            self._scheduled_polls = sample_quantiles(
                cdf_times,
                cdf_probs,
                cdf_budget,
                condition_above=condition_on_elapsed,
            )

        # Merge forced polls into schedule (deduplicate and sort)
        if forced_polls:
            all_polls = sorted(set(self._scheduled_polls + forced_polls))
            self._scheduled_polls = all_polls
