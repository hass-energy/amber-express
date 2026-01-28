"""CDF-based polling strategy for optimal confirmatory poll timing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, TypedDict


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

    Cold start: Uses synthetic observations centered around [15s, 45s] until real
    data is collected.
    """

    # Configuration constants
    WINDOW_SIZE = 100  # Rolling window of observations (N)
    DEFAULT_POLLS_PER_INTERVAL = 4  # Default number of polls per interval (k)
    MIN_POLLS_PER_INTERVAL = 1  # Minimum polls per interval
    MIN_CDF_POINTS = 2  # Minimum points required for a valid CDF
    COLD_START_INTERVAL: ClassVar[IntervalObservation] = {"start": 15.0, "end": 45.0}

    def __init__(self, observations: list[IntervalObservation] | None = None) -> None:
        """Initialize the strategy with optional pre-loaded observations."""
        if observations is not None:
            self._observations = observations[-self.WINDOW_SIZE :]
        else:
            # Cold start: fill with synthetic intervals
            self._observations = [self.COLD_START_INTERVAL.copy() for _ in range(self.WINDOW_SIZE)]

        self._scheduled_polls: list[float] = []
        self._next_poll_index = 0
        self._confirmatory_poll_count = 0
        self._polls_per_interval = self.DEFAULT_POLLS_PER_INTERVAL

        # Pre-compute schedule for first interval
        self._compute_poll_schedule()

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
            self._polls_per_interval = max(self.MIN_POLLS_PER_INTERVAL, polls_per_interval)
            # Recompute schedule with new k
            self._compute_poll_schedule()

    def update_budget(self, polls_per_interval: int, elapsed_seconds: float) -> None:
        """Update the poll budget mid-interval based on new rate limit info.

        Recomputes the schedule using conditional probability - since we know
        the event hasn't occurred by elapsed_seconds, we sample from P(T | T > t).

        Args:
            polls_per_interval: New number of confirmatory polls (from remaining quota)
            elapsed_seconds: Current elapsed time in the interval

        """
        self._polls_per_interval = max(self.MIN_POLLS_PER_INTERVAL, polls_per_interval)
        self._compute_poll_schedule(condition_on_elapsed=elapsed_seconds)
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

    def _compute_poll_schedule(self, condition_on_elapsed: float | None = None) -> None:
        """Compute optimal poll times using inverse CDF sampling.

        Args:
            condition_on_elapsed: If provided, compute conditional schedule given
                that the event hasn't occurred by this time. Uses P(T | T > t).

        """
        if not self._observations:
            self._scheduled_polls = []
            return

        # Build the CDF
        cdf_points = self._build_cdf()

        if len(cdf_points) < self.MIN_CDF_POINTS:
            self._scheduled_polls = []
            return

        # Compute poll times via inverse CDF
        k = self._polls_per_interval

        if condition_on_elapsed is not None and condition_on_elapsed > 0:
            # Conditional sampling: we know T > elapsed, so sample from P(T | T > t)
            # F_conditional(x) = (F(x) - F(t)) / (1 - F(t))
            # To sample, we need F^-1(F(t) + p * (1 - F(t)))
            f_elapsed = self._cdf_at(condition_on_elapsed, cdf_points)

            if f_elapsed >= 1.0:
                # All probability mass is before elapsed - shouldn't happen
                self._scheduled_polls = []
                return

            # Map uniform [0,1] targets to conditional targets
            remaining_mass = 1.0 - f_elapsed
            target_probabilities = [f_elapsed + (j / (k + 1)) * remaining_mass for j in range(1, k + 1)]
        else:
            # Unconditional sampling
            target_probabilities = [j / (k + 1) for j in range(1, k + 1)]

        self._scheduled_polls = [self._inverse_cdf(p, cdf_points) for p in target_probabilities]

    def _build_cdf(self) -> list[tuple[float, float]]:
        """Build piecewise linear CDF from interval observations.

        Returns:
            List of (time, cumulative_probability) points defining the CDF.

        """
        if not self._observations:
            return []

        n = len(self._observations)

        # Collect all unique endpoints
        endpoints: set[float] = set()
        for obs in self._observations:
            endpoints.add(obs["start"])
            endpoints.add(obs["end"])

        # Sort to form time grid
        time_grid = sorted(endpoints)

        if len(time_grid) < self.MIN_CDF_POINTS:
            return []

        # For each segment, compute the CDF slope (sum of contributing densities)
        # Each interval [a_i, b_i] contributes density 1/(N * (b_i - a_i)) when t in [a_i, b_i)
        cdf_points: list[tuple[float, float]] = [(time_grid[0], 0.0)]
        cumulative = 0.0

        for i in range(len(time_grid) - 1):
            t_start = time_grid[i]
            t_end = time_grid[i + 1]
            segment_length = t_end - t_start

            # Compute slope: sum of densities from intervals covering this segment
            slope = 0.0
            for obs in self._observations:
                a, b = obs["start"], obs["end"]
                if a <= t_start < b:
                    # This interval contributes to this segment
                    slope += 1.0 / (n * (b - a))

            # Integrate: add slope * segment_length to cumulative
            cumulative += slope * segment_length
            cdf_points.append((t_end, cumulative))

        # Normalize so CDF ends at 1.0
        if cumulative > 0:
            cdf_points = [(t, p / cumulative) for t, p in cdf_points]

        return cdf_points

    def _cdf_at(self, t: float, cdf_points: list[tuple[float, float]]) -> float:
        """Compute CDF value F(t) at a given time via linear interpolation.

        Args:
            t: Time to evaluate CDF at
            cdf_points: List of (time, cumulative_probability) points

        Returns:
            F(t) - the cumulative probability at time t

        """
        if not cdf_points:
            return 0.0

        # Before first point
        if t <= cdf_points[0][0]:
            return cdf_points[0][1]

        # After last point
        if t >= cdf_points[-1][0]:
            return cdf_points[-1][1]

        # Find segment containing t and interpolate
        # CDF is contiguous so a matching segment always exists when t is in range
        for i in range(len(cdf_points) - 1):
            t0, p0 = cdf_points[i]
            t1, p1 = cdf_points[i + 1]

            if t0 <= t <= t1:
                fraction = (t - t0) / (t1 - t0)
                return p0 + fraction * (p1 - p0)

        return cdf_points[-1][1]

    def _inverse_cdf(self, target_p: float, cdf_points: list[tuple[float, float]]) -> float:
        """Compute inverse CDF (quantile function) via linear interpolation.

        Args:
            target_p: Target probability in [0, 1]
            cdf_points: List of (time, cumulative_probability) points

        Returns:
            Time t such that F(t) = target_p

        """
        if not cdf_points:
            return 0.0

        # Handle edge cases
        if target_p <= cdf_points[0][1]:
            return cdf_points[0][0]
        if target_p >= cdf_points[-1][1]:
            return cdf_points[-1][0]

        # Find segment containing target_p
        # CDF is strictly increasing so a matching segment always exists
        for i in range(len(cdf_points) - 1):
            t0, p0 = cdf_points[i]
            t1, p1 = cdf_points[i + 1]

            if p0 <= target_p <= p1:
                fraction = (target_p - p0) / (p1 - p0)
                return t0 + fraction * (t1 - t0)

        return cdf_points[-1][0]
