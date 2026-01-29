"""Pure CDF algorithm functions for optimal poll timing.

This module contains stateless functions for building empirical CDFs from
interval observations and computing optimal poll times via inverse CDF sampling.
These functions have no side effects and can be tested in isolation.
"""

from __future__ import annotations

from typing import Required, TypedDict

import numpy as np
from numpy.typing import NDArray


class IntervalObservation(TypedDict, total=False):
    """An observed interval where the confirmed price became available."""

    start: Required[float]  # Last poll time that returned estimate
    end: Required[float]  # First poll time that returned confirmed
    weight: float  # Contribution weight (defaults to 1.0)


def build_cdf(
    observations: list[IntervalObservation],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Build piecewise linear CDF from interval observations.

    Each observation [start, end] represents an interval where the event
    occurred somewhere within. The CDF is built by treating each interval
    as a uniform distribution and weighting by the observation's weight field.

    Args:
        observations: List of interval observations with non-zero width.
            Each observation may have an optional 'weight' field (defaults
            to 1.0) that determines its contribution to the CDF.

    Returns:
        Tuple of (times array, cumulative probability array) defining the CDF.

    """
    # Extract starts, ends, and weights as numpy arrays
    starts = np.array([obs["start"] for obs in observations], dtype=np.float64)
    ends = np.array([obs["end"] for obs in observations], dtype=np.float64)
    weights = np.array([obs.get("weight", 1.0) for obs in observations], dtype=np.float64)
    total_weight = np.sum(weights)

    # Collect all unique endpoints and sort to form time grid
    time_grid = np.unique(np.concatenate([starts, ends]))

    # Compute individual CDFs for all observations and take weighted average
    individual_cdfs = np.clip((time_grid - starts[:, np.newaxis]) / (ends - starts)[:, np.newaxis], 0.0, 1.0)
    cumulative = np.sum(individual_cdfs * weights[:, np.newaxis], axis=0) / total_weight

    return time_grid, cumulative


def compute_poll_times(
    cdf_times: NDArray[np.float64],
    cdf_probs: NDArray[np.float64],
    k: int,
    *,
    condition_on_elapsed: float | None = None,
) -> list[float]:
    """Compute optimal poll times using inverse CDF sampling.

    Places k polls at quantile positions 1/(k+1), 2/(k+1), ..., k/(k+1) of the CDF.
    Optionally conditions on elapsed time for mid-interval schedule updates.

    Args:
        cdf_times: Time values of the CDF
        cdf_probs: Cumulative probability values of the CDF
        k: Number of polls to schedule
        condition_on_elapsed: If provided, compute conditional schedule given
            that the event hasn't occurred by this time. Uses P(T | T > t).

    Returns:
        List of poll times in seconds from interval start.

    """
    if k <= 0:
        return []

    # Quantile positions for k polls
    j_values = np.arange(1, k + 1)
    quantile_probs = j_values / (k + 1)

    if condition_on_elapsed is not None and condition_on_elapsed > 0:
        # Conditional sampling: we know T > elapsed, so sample from P(T | T > t)
        # F_conditional(x) = (F(x) - F(t)) / (1 - F(t))
        # To sample, we need F^-1(F(t) + p * (1 - F(t)))
        f_elapsed = float(np.interp(condition_on_elapsed, cdf_times, cdf_probs))

        if f_elapsed >= 1.0:
            # All probability mass is before elapsed - no valid polls
            return []

        # Map uniform [0,1] targets to conditional targets
        remaining_mass = 1.0 - f_elapsed
        target_probabilities = f_elapsed + quantile_probs * remaining_mass
    else:
        # Unconditional sampling
        target_probabilities = quantile_probs

    # Compute poll times from inverse CDF
    # For inverse CDF, we interpolate with x=probs, y=times
    poll_times = np.interp(target_probabilities, cdf_probs, cdf_times)

    return poll_times.tolist()
