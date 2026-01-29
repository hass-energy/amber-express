"""Tests for CDF algorithm functions."""

from __future__ import annotations

import numpy as np
import pytest

from custom_components.amber_express.cdf_algorithm import IntervalObservation, build_cdf, sample_quantiles


class TestSampleQuantiles:
    """Tests for sample_quantiles function."""

    def test_returns_empty_when_n_is_zero(self) -> None:
        """Test that n=0 returns an empty list."""
        cdf_x = np.array([10.0, 20.0, 30.0])
        cdf_y = np.array([0.0, 0.5, 1.0])

        result = sample_quantiles(cdf_x, cdf_y, n=0)

        assert result == []

    def test_returns_empty_when_n_is_negative(self) -> None:
        """Test that negative n returns an empty list."""
        cdf_x = np.array([10.0, 20.0, 30.0])
        cdf_y = np.array([0.0, 0.5, 1.0])

        result = sample_quantiles(cdf_x, cdf_y, n=-5)

        assert result == []

    def test_returns_empty_when_condition_above_exceeds_cdf(self) -> None:
        """Test that conditioning past entire CDF returns empty list."""
        cdf_x = np.array([10.0, 20.0, 30.0])
        cdf_y = np.array([0.0, 0.5, 1.0])

        # condition_above=35 is past the CDF end (30), so F(35) = 1.0
        result = sample_quantiles(cdf_x, cdf_y, n=4, condition_above=35.0)

        assert result == []

    def test_returns_samples_for_positive_n(self) -> None:
        """Test that positive n returns correct number of samples."""
        cdf_x = np.array([0.0, 10.0])
        cdf_y = np.array([0.0, 1.0])

        result = sample_quantiles(cdf_x, cdf_y, n=4)

        assert len(result) == 4
        # For uniform [0, 10], quantiles at 1/5, 2/5, 3/5, 4/5 = [2, 4, 6, 8]
        assert result == [2.0, 4.0, 6.0, 8.0]

    def test_conditional_sampling_shifts_distribution(self) -> None:
        """Test that condition_above samples from remaining mass."""
        cdf_x = np.array([0.0, 10.0])
        cdf_y = np.array([0.0, 1.0])

        # Condition on X > 5, so F(5) = 0.5, remaining mass = 0.5
        result = sample_quantiles(cdf_x, cdf_y, n=3, condition_above=5.0)

        assert len(result) == 3
        # All samples should be > 5
        assert all(x > 5.0 for x in result)
        # Quantiles in [5, 10]: 1/4, 2/4, 3/4 of [5, 10] = [6.25, 7.5, 8.75]
        assert result == pytest.approx([6.25, 7.5, 8.75])


class TestBuildCdf:
    """Additional tests for build_cdf function."""

    def test_empty_observations(self) -> None:
        """Test build_cdf returns empty arrays with no observations."""
        cdf_times, cdf_probs = build_cdf([])

        assert len(cdf_times) == 0
        assert len(cdf_probs) == 0

    def test_single_observation(self) -> None:
        """Test build_cdf with single observation produces valid CDF."""
        observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]

        cdf_times, cdf_probs = build_cdf(observations)

        # Should have 2 points: start and end
        assert len(cdf_times) == 2
        assert list(cdf_times) == [10.0, 20.0]
        assert list(cdf_probs) == [0.0, 1.0]
