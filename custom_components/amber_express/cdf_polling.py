"""CDF-based polling strategy for optimal confirmatory poll timing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

import numpy as np
from numpy.typing import NDArray

from .cdf_cold_start import COLD_START_OBSERVATIONS


class IntervalObservation(TypedDict):
    """An observed interval where the confirmed price became available."""

    start: float  # Last poll time that returned estimate
    end: float  # First poll time that returned confirmed


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
    """Statistical algorithm that learns optimal poll times from historical observations.

    Responsibilities:
    - Maintaining a rolling window of interval observations [start, end]
    - Building an empirical Cumulative Distribution Function (CDF) from observations
    - Computing optimal poll times via inverse CDF sampling
    - Tracking scheduled polls and which have been executed
    - Supporting mid-interval budget updates with conditional probability

    The CDF represents "probability that confirmed price arrived by time t". Given
    k polls to schedule, we place them at times where F(t) = 1/(k+1), 2/(k+1), etc.
    This minimizes expected detection delay under the learned distribution.

    This class is a pure algorithm with no dependencies on Home Assistant or the
    Amber API. It only knows about time intervals and probability distributions.

    Cold start: Uses real observations from historical data until real-time
    data is collected.
    """

    # Configuration constants
    WINDOW_SIZE = 100  # Rolling window of observations (N)
    MIN_CDF_POINTS = 2  # Minimum points required for a valid CDF

    # Uniform blending thresholds as fractions of quota: blend targeted CDF with
    # uniform distribution based on remaining poll budget (k) to spread polls when low
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
            self._compute_poll_schedule()

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
        self._compute_poll_schedule(
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
            # Invalid observation, skip
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
        self._compute_poll_schedule()

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

    def _compute_poll_schedule(
        self,
        condition_on_elapsed: float | None = None,
        reset_seconds: int | None = None,
    ) -> None:
        """Compute optimal poll times using inverse CDF sampling with quantile blending.

        When poll budget (k) is low, blends targeted poll times with uniform
        distribution to spread polls evenly. Uses quantile blending: each poll
        time is interpolated between targeted and uniform positions.

        Args:
            condition_on_elapsed: If provided, compute conditional schedule given
                that the event hasn't occurred by this time. Uses P(T | T > t).
            reset_seconds: Seconds until rate limit resets. Used for uniform
                distribution endpoint when blending.

        """
        if not self._observations:
            self._scheduled_polls = []
            return

        # Build the CDF (uses cache if available)
        cdf_times, cdf_probs = self._build_cdf()

        if len(cdf_times) < self.MIN_CDF_POINTS:
            self._scheduled_polls = []
            return

        # Compute poll times via inverse CDF
        k = self._polls_per_interval

        # Compute blend weight early - we may need pure uniform fallback
        w = self._compute_blend_weight(k)
        uniform_start = condition_on_elapsed if condition_on_elapsed else 0.0

        # Quantile positions for k polls
        j_values = np.arange(1, k + 1)
        uniform_probs = j_values / (k + 1)

        if condition_on_elapsed is not None and condition_on_elapsed > 0:
            # Conditional sampling: we know T > elapsed, so sample from P(T | T > t)
            # F_conditional(x) = (F(x) - F(t)) / (1 - F(t))
            # To sample, we need F^-1(F(t) + p * (1 - F(t)))
            f_elapsed = float(np.interp(condition_on_elapsed, cdf_times, cdf_probs))

            if f_elapsed >= 1.0:
                # All probability mass is before elapsed - use pure uniform if blending enabled
                if w < 1.0 and reset_seconds is not None:
                    uniform_end = uniform_start + reset_seconds
                    self._scheduled_polls = (uniform_start + uniform_probs * (uniform_end - uniform_start)).tolist()
                else:
                    self._scheduled_polls = []
                return

            # Map uniform [0,1] targets to conditional targets
            remaining_mass = 1.0 - f_elapsed
            target_probabilities = f_elapsed + uniform_probs * remaining_mass
        else:
            # Unconditional sampling
            target_probabilities = uniform_probs

        # Compute targeted poll times from inverse CDF
        # For inverse CDF, we interpolate with x=probs, y=times
        targeted_polls = np.interp(target_probabilities, cdf_probs, cdf_times)

        if w >= 1.0 or reset_seconds is None:
            # Pure targeted CDF (no blending needed)
            self._scheduled_polls = targeted_polls.tolist()
        else:
            # Blend targeted with uniform distribution
            # Uniform spans from elapsed to reset time
            uniform_end = uniform_start + reset_seconds
            uniform_times = uniform_start + uniform_probs * (uniform_end - uniform_start)
            blended = w * targeted_polls + (1 - w) * uniform_times
            self._scheduled_polls = blended.tolist()

    def _build_cdf(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Build piecewise linear CDF from interval observations.

        Returns:
            Tuple of (times array, cumulative probability array) defining the CDF.

        """
        # Return cached CDF if available
        if self._cdf_times is not None and self._cdf_probs is not None:
            return self._cdf_times, self._cdf_probs

        if not self._observations:
            empty = np.array([], dtype=np.float64)
            return empty, empty

        n = len(self._observations)

        # Extract starts and ends as numpy arrays
        starts = np.array([obs["start"] for obs in self._observations], dtype=np.float64)
        ends = np.array([obs["end"] for obs in self._observations], dtype=np.float64)

        # Collect all unique endpoints and sort to form time grid
        time_grid = np.unique(np.concatenate([starts, ends]))

        if len(time_grid) < self.MIN_CDF_POINTS:
            empty = np.array([], dtype=np.float64)
            return empty, empty

        # For each segment [t_i, t_{i+1}), check which intervals contain the segment start
        segment_starts = time_grid[:-1]

        # Boolean mask: covers[i, j] = True if observation j covers segment i
        covers = (starts <= segment_starts[:, np.newaxis]) & (segment_starts[:, np.newaxis] < ends)

        # Compute density for each observation: 1 / (n * (end - start))
        densities = 1.0 / (n * (ends - starts))

        # Compute slope for each segment: sum of densities for covering observations
        slopes = np.sum(covers * densities, axis=1)

        # Compute segment lengths
        segment_lengths = time_grid[1:] - time_grid[:-1]

        # Integrate: cumulative sum of slope * length
        cumulative = np.concatenate([[0.0], np.cumsum(slopes * segment_lengths)])

        # Normalize so CDF ends at 1.0
        if cumulative[-1] > 0:
            cumulative = cumulative / cumulative[-1]

        # Cache the result
        self._cdf_times = time_grid
        self._cdf_probs = cumulative

        return time_grid, cumulative

    def _compute_blend_weight(self, k: int) -> float:
        """Compute weight for blending targeted CDF vs uniform distribution.

        Uses clamped linear interpolation between K_LOW and K_HIGH, which are
        computed dynamically from the rate limit quota.

        At k >= K_HIGH (60% of quota): returns 1.0 (pure targeted CDF)
        At k <= K_LOW (20% of quota): returns 0.0 (pure uniform distribution)
        In between: linear interpolation

        Args:
            k: Number of polls remaining (poll budget)

        Returns:
            Weight in [0.0, 1.0] for targeted CDF contribution

        """
        # Before first update_budget call, use pure targeted CDF (no blending)
        if self._quota is None:
            return 1.0

        k_high = int(self._quota * self.UNIFORM_BLEND_FRACTION_HIGH)
        k_low = int(self._quota * self.UNIFORM_BLEND_FRACTION_LOW)

        if k >= k_high:
            return 1.0
        if k <= k_low:
            return 0.0
        return (k - k_low) / (k_high - k_low)
