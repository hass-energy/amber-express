"""Tests for the smart polling manager."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from custom_components.amber_express.cdf_cold_start import COLD_START_OBSERVATIONS
from custom_components.amber_express.cdf_polling import IntervalObservation
from custom_components.amber_express.smart_polling import PollingState, SmartPollingManager
from custom_components.amber_express.types import RateLimitInfo


class TestSmartPollingManagerInit:
    """Tests for SmartPollingManager initialization."""

    def test_initial_state(self) -> None:
        """Test initial state after construction."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))
        state = manager.get_state()

        assert state.current_interval_start is None
        assert state.has_confirmed_price is False
        assert state.poll_count_this_interval == 0
        assert state.first_interval_after_startup is True
        assert state.last_estimate_elapsed is None

    def test_initial_properties(self) -> None:
        """Test initial property values."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        assert manager.has_confirmed_price is False
        assert manager.poll_count_this_interval == 0
        assert manager.first_interval_after_startup is True


class TestShouldPoll:
    """Tests for should_poll method."""

    def test_first_run_always_polls(self) -> None:
        """Test that first run (no data) always polls."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        result = manager.should_poll(has_data=False)

        assert result is True

    def test_new_interval_always_polls(self) -> None:
        """Test that new interval always triggers polling."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # First poll at 10:00
            result1 = manager.should_poll(has_data=True)
            assert result1 is True

            # Same interval, confirmed price
            manager.on_confirmed_received()

            # Move to next interval at 10:05
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
            result2 = manager.should_poll(has_data=True)
            assert result2 is True

    def test_confirmed_price_stops_polling(self) -> None:
        """Test that confirmed price stops polling."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Start interval
            manager.should_poll(has_data=True)

            # Receive confirmed price
            manager.on_confirmed_received()

            # Check if should poll - should be False
            result = manager.should_poll(has_data=True)
            assert result is False

    def test_cdf_scheduled_polling_after_first_poll(self) -> None:
        """Test that polling uses CDF scheduled times after first poll."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))
        # remaining=10 gives us 5 polls after the buffer of 5 is subtracted
        # 1 poll reserved for interval end (300s), leaving 4 CDF polls
        # With cdf_budget=4 and reset=300, uniform_polls_needed = ceil(300/30) = 10
        # Since 4 <= 10, uses pure uniform: 4 polls at 60, 120, 180, 240 + forced at 300

        with (
            patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime,
            patch("custom_components.amber_express.cdf_polling.datetime") as mock_cdf_datetime,
        ):
            base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            mock_datetime.now.return_value = base_time
            mock_cdf_datetime.now.return_value = base_time

            # Create rate_limit_info with reset_at based on the mocked time
            rate_limit_info: RateLimitInfo = {
                "limit": 50,
                "remaining": 10,
                "reset_at": base_time + timedelta(seconds=300),
                "window_seconds": 300,
                "policy": "50;w=300",
            }

            # First poll starts the interval
            result1 = manager.should_poll(has_data=True)
            assert result1 is True

            # Update budget after first poll
            manager.update_budget(rate_limit_info)

            # 5 seconds later - before first scheduled poll at 60s
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 5, tzinfo=UTC)
            result2 = manager.should_poll(has_data=True)
            assert result2 is False  # Not yet time

            # 60 seconds - first scheduled poll
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 1, 0, tzinfo=UTC)
            result3 = manager.should_poll(has_data=True)
            assert result3 is True  # Time to poll


class TestPollLifecycle:
    """Tests for poll lifecycle methods."""

    def test_on_poll_started_increments_count(self) -> None:
        """Test that on_poll_started increments poll count."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        assert manager.poll_count_this_interval == 0

        manager.on_poll_started()
        assert manager.poll_count_this_interval == 1

        manager.on_poll_started()
        assert manager.poll_count_this_interval == 2

    def test_on_estimate_received_records_elapsed(self) -> None:
        """Test that on_estimate_received records elapsed time."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Start interval
            manager.should_poll(has_data=True)

            # 10 seconds later, receive estimate
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 10, tzinfo=UTC)
            manager.on_estimate_received()

            state = manager.get_state()
            assert state.last_estimate_elapsed == 10.0

    def test_on_confirmed_received_sets_flag(self) -> None:
        """Test that on_confirmed_received sets has_confirmed_price."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        assert manager.has_confirmed_price is False

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)

            manager.on_confirmed_received()

        assert manager.has_confirmed_price is True


class TestIntervalReset:
    """Tests for interval reset behavior."""

    def test_new_interval_resets_state(self) -> None:
        """Test that moving to a new interval resets all state."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            # Start first interval
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)
            manager.on_poll_started()
            manager.on_poll_started()
            manager.on_confirmed_received()

            # Verify state is set
            assert manager.has_confirmed_price is True
            assert manager.poll_count_this_interval == 2

            # Move to next interval
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)

            # Verify state is reset
            assert manager.has_confirmed_price is False
            assert manager.poll_count_this_interval == 0

    def test_first_interval_flag_clears_on_second_interval(self) -> None:
        """Test that first_interval_after_startup clears on second interval."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        assert manager.first_interval_after_startup is True

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            # First interval with has_data=False (first run)
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=False)  # First run
            # Note: first_interval_after_startup remains True until SECOND interval

            # Second interval with has_data=True (not first run)
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)  # Now has data
            assert manager.first_interval_after_startup is False


class TestGetCDFStats:
    """Tests for get_cdf_stats method."""

    def test_returns_cdf_strategy_stats(self) -> None:
        """Test that get_cdf_stats returns stats from CDF strategy."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))
        # remaining=9 gives us 4 polls after the buffer of 5 is subtracted
        rate_limit_info: RateLimitInfo = {
            "limit": 50,
            "remaining": 9,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)
            manager.update_budget(rate_limit_info)

        stats = manager.get_cdf_stats()

        assert stats.observation_count == 100  # Cold start real observations
        assert stats.confirmatory_poll_count == 0
        # k=4 total: 3 CDF polls + 1 forced at interval end = 4 total
        assert len(stats.scheduled_polls) == 4
        assert stats.scheduled_polls[-1] == 300.0


class TestPollingState:
    """Tests for PollingState dataclass."""

    def test_polling_state_fields(self) -> None:
        """Test PollingState dataclass fields."""
        state = PollingState(
            current_interval_start=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            has_confirmed_price=True,
            poll_count_this_interval=3,
            first_interval_after_startup=False,
            last_estimate_elapsed=10.5,
        )

        assert state.current_interval_start == datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert state.has_confirmed_price is True
        assert state.poll_count_this_interval == 3
        assert state.first_interval_after_startup is False
        assert state.last_estimate_elapsed == 10.5


class TestRateLimitBasedPolling:
    """Tests for rate limit based k calculation."""

    def test_calculate_polls_subtracts_buffer(self) -> None:
        """Test k equals remaining minus buffer from rate limit info."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))
        buffer = manager.RATE_LIMIT_BUFFER  # Currently 5

        base_info: RateLimitInfo = {
            "limit": 50,
            "remaining": 45,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        result = manager._calculate_polls_per_interval(base_info)
        assert result == 45 - buffer  # 40

        result = manager._calculate_polls_per_interval({**base_info, "remaining": 10})
        assert result == 10 - buffer  # 5

        # At or below buffer, result is 0
        result = manager._calculate_polls_per_interval({**base_info, "remaining": 5})
        assert result == 0

        result = manager._calculate_polls_per_interval({**base_info, "remaining": 1})
        assert result == 0

    def test_update_budget_uses_rate_limit_info(self) -> None:
        """Test that update_budget uses rate limit info for k calculation."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))
        buffer = manager.RATE_LIMIT_BUFFER

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Trigger new interval
            result = manager.should_poll(has_data=True)
            assert result is True

            # Update budget with 45 remaining
            manager.update_budget(
                {
                    "limit": 50,
                    "remaining": 45,
                    "reset_at": datetime.now(UTC) + timedelta(seconds=300),
                    "window_seconds": 300,
                    "policy": "50;w=300",
                }
            )

            # k=40 total: 39 CDF polls + 1 forced at interval end = 40 total
            stats = manager.get_cdf_stats()
            assert len(stats.scheduled_polls) == 45 - buffer
            assert stats.scheduled_polls[-1] == 300.0

    def test_update_budget_dynamically_adjusts_schedule(self) -> None:
        """Test that update_budget dynamically adjusts the schedule mid-interval."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))
        buffer = manager.RATE_LIMIT_BUFFER

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Trigger new interval
            manager.should_poll(has_data=True)

            # k=40 total: 39 CDF polls + 1 forced at interval end = 40 total
            manager.update_budget(
                {
                    "limit": 50,
                    "remaining": 45,
                    "reset_at": datetime.now(UTC) + timedelta(seconds=300),
                    "window_seconds": 300,
                    "policy": "50;w=300",
                }
            )
            assert len(manager.get_cdf_stats().scheduled_polls) == 45 - buffer

            # Time passes, budget shrinks to 15 (10 after buffer)
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 15, tzinfo=UTC)
            manager.update_budget(
                {
                    "limit": 50,
                    "remaining": 15,
                    "reset_at": datetime.now(UTC) + timedelta(seconds=285),
                    "window_seconds": 300,
                    "policy": "50;w=300",
                }
            )

            # k=10 total: 9 CDF polls + 1 forced at interval end = 10 total
            assert len(manager.get_cdf_stats().scheduled_polls) == 15 - buffer


class TestGetNextPollDelay:
    """Tests for get_next_poll_delay method."""

    def test_get_next_poll_delay_when_confirmed(self) -> None:
        """Test delay returns None when confirmed price received."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)
            manager.on_confirmed_received()

            delay = manager.get_next_poll_delay()
            assert delay is None

    def test_get_next_poll_delay_no_interval(self) -> None:
        """Test delay returns None before interval starts."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        # No interval started yet
        delay = manager.get_next_poll_delay()
        assert delay is None

    def test_get_next_poll_delay_returns_seconds(self) -> None:
        """Test delay returns seconds until next poll."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))
        # remaining=9 gives us 4 polls after buffer of 5
        rate_limit_info: RateLimitInfo = {
            "limit": 50,
            "remaining": 9,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)
            manager.update_budget(rate_limit_info)

            # Get first scheduled poll time from CDF stats
            first_poll = manager.get_cdf_stats().scheduled_polls[0]

            # At 5s elapsed, delay should be (first_poll - 5)
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 5, tzinfo=UTC)
            delay = manager.get_next_poll_delay()
            assert delay is not None
            assert abs(delay - (first_poll - 5.0)) < 0.001


class TestObservationsProperty:
    """Tests for observations property."""

    def test_observations_returns_copy(self) -> None:
        """Test observations property returns a copy."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        obs1 = manager.observations
        obs2 = manager.observations

        assert obs1 == obs2
        assert obs1 is not obs2

    def test_observations_with_preloaded(self) -> None:
        """Test observations initialized with preloaded data."""
        observations: list[IntervalObservation] = [
            {"start": 10.0, "end": 20.0},
            {"start": 15.0, "end": 25.0},
        ]
        manager = SmartPollingManager(5, observations)

        result = manager.observations
        assert len(result) == 2
        assert result[0]["start"] == 10.0


class TestObservationRecording:
    """Tests for observation recording edge cases."""

    def test_confirmed_without_estimate_skips_observation(self) -> None:
        """Test confirmed without prior estimate doesn't record observation."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)

            # Force past first interval flag
            manager._first_interval_after_startup = False

            # Receive confirmed without estimate
            manager.on_confirmed_received()

            # Observation count should remain at cold start
            stats = manager.get_cdf_stats()
            # Cold start has 100 observations, confirm without estimate doesn't add
            assert stats.observation_count == 100

    def test_confirmed_with_estimate_records_observation(self) -> None:
        """Test confirmed with prior estimate records observation."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)

            # Force past first interval flag
            manager._first_interval_after_startup = False

            # Receive estimate then confirmed
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 10, tzinfo=UTC)
            manager.on_estimate_received()

            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 25, tzinfo=UTC)
            manager.on_confirmed_received()

            # Should have recorded observation
            stats = manager.get_cdf_stats()
            assert stats.last_observation is not None
            assert stats.last_observation["start"] == 10.0
            assert stats.last_observation["end"] == 25.0


class TestUpdateBudgetEdgeCases:
    """Tests for update_budget edge cases."""

    def test_update_budget_no_interval(self) -> None:
        """Test update_budget before interval starts."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        # Should not crash
        manager.update_budget(
            {
                "limit": 50,
                "remaining": 10,
                "reset_at": datetime.now(UTC) + timedelta(seconds=300),
                "window_seconds": 300,
                "policy": "50;w=300",
            }
        )


class TestCheckNewInterval:
    """Tests for check_new_interval method."""

    def test_check_new_interval_first_call(self) -> None:
        """Test check_new_interval on first call."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            result = manager.check_new_interval(has_data=False)
            assert result is True

    def test_check_new_interval_same_interval(self) -> None:
        """Test check_new_interval returns False for same interval."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.check_new_interval(has_data=True)

            # Same interval
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 2, 30, tzinfo=UTC)
            result = manager.check_new_interval(has_data=True)
            assert result is False

    def test_update_budget_after_new_interval(self) -> None:
        """Test update_budget computes schedule after new interval."""
        manager = SmartPollingManager(5, list(COLD_START_OBSERVATIONS))
        buffer = manager.RATE_LIMIT_BUFFER

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Start new interval
            result = manager.check_new_interval(has_data=True)
            assert result is True

            # Update budget with remaining=15 gives us 10 polls after buffer
            manager.update_budget(
                {
                    "limit": 50,
                    "remaining": 15,
                    "reset_at": datetime.now(UTC) + timedelta(seconds=300),
                    "window_seconds": 300,
                    "policy": "50;w=300",
                }
            )

            # k=10 total: 9 CDF polls + 1 forced at interval end = 10 total
            stats = manager.get_cdf_stats()
            assert len(stats.scheduled_polls) == 15 - buffer
