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


def sample_quantiles(
    cdf_x: NDArray[np.float64],
    cdf_y: NDArray[np.float64],
    n: int,
    *,
    condition_above: float | None = None,
) -> list[float]:
    """Sample n quantile positions from a CDF using inverse CDF sampling.

    Places n samples at quantile positions 1/(n+1), 2/(n+1), ..., n/(n+1).
    Optionally conditions on a lower bound (samples from the conditional
    distribution given X > lower_bound).

    Args:
        cdf_x: X values of the CDF
        cdf_y: Cumulative probability values of the CDF
        n: Number of samples
        condition_above: If provided, sample from conditional distribution
            P(X | X > condition_above).

    Returns:
        List of sampled values.

    """
    if n <= 0:
        return []

    quantiles = np.arange(1, n + 1) / (n + 1)

    if condition_above is not None and condition_above > 0:
        # Conditional sampling from P(X | X > t)
        f_t = float(np.interp(condition_above, cdf_x, cdf_y))

        if f_t >= 1.0:
            return []

        remaining_mass = 1.0 - f_t
        target_probs = f_t + quantiles * remaining_mass
    else:
        target_probs = quantiles

    samples = np.interp(target_probs, cdf_y, cdf_x)

    return samples.tolist()
