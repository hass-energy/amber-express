"""Tests for the smart polling manager."""

from datetime import UTC, datetime
from unittest.mock import patch

from custom_components.amber_express.cdf_polling import IntervalObservation
from custom_components.amber_express.smart_polling import PollingState, SmartPollingManager


class TestSmartPollingManagerInit:
    """Tests for SmartPollingManager initialization."""

    def test_initial_state(self) -> None:
        """Test initial state after construction."""
        manager = SmartPollingManager(5)
        state = manager.get_state()

        assert state.current_interval_start is None
        assert state.has_confirmed_price is False
        assert state.forecasts_pending is False
        assert state.poll_count_this_interval == 0
        assert state.first_interval_after_startup is True
        assert state.last_estimate_elapsed is None

    def test_initial_properties(self) -> None:
        """Test initial property values."""
        manager = SmartPollingManager(5)

        assert manager.has_confirmed_price is False
        assert manager.forecasts_pending is False
        assert manager.poll_count_this_interval == 0
        assert manager.first_interval_after_startup is True


class TestShouldPoll:
    """Tests for should_poll method."""

    def test_first_run_always_polls(self) -> None:
        """Test that first run (no data) always polls."""
        manager = SmartPollingManager(5)

        result = manager.should_poll(has_data=False)

        assert result is True

    def test_new_interval_always_polls(self) -> None:
        """Test that new interval always triggers polling."""
        manager = SmartPollingManager(5)

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
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Start interval
            manager.should_poll(has_data=True)

            # Receive confirmed price
            manager.on_confirmed_received()

            # Check if should poll - should be False
            result = manager.should_poll(has_data=True)
            assert result is False

    def test_forecasts_pending_allows_retry(self) -> None:
        """Test that forecasts pending allows retry polling."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Start interval
            manager.should_poll(has_data=True)

            # Receive confirmed price but forecasts failed
            manager.on_confirmed_received()
            manager.set_forecasts_pending()

            # Should poll to retry forecasts
            result = manager.should_poll(has_data=True)
            assert result is True

    def test_forecasts_pending_respects_rate_limit(self) -> None:
        """Test that forecasts pending respects rate limit."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Start interval
            manager.should_poll(has_data=True)

            # Receive confirmed price but forecasts failed
            manager.on_confirmed_received()
            manager.set_forecasts_pending()

            # Set rate limit until 10:01
            rate_limit_until = datetime(2024, 1, 1, 10, 1, 0, tzinfo=UTC)

            # Still at 10:00 - should not poll
            result = manager.should_poll(has_data=True, rate_limit_until=rate_limit_until)
            assert result is False

    def test_cdf_scheduled_polling_after_first_poll(self) -> None:
        """Test that polling uses CDF scheduled times after first poll."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # First poll starts the interval
            result1 = manager.should_poll(has_data=True)
            assert result1 is True

            # 5 seconds later - before first scheduled poll at 21s
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 5, tzinfo=UTC)
            result2 = manager.should_poll(has_data=True)
            assert result2 is False  # Not yet time

            # 21 seconds - first scheduled poll (cold start: 21, 27, 33, 39)
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 21, tzinfo=UTC)
            result3 = manager.should_poll(has_data=True)
            assert result3 is True  # Time to poll


class TestPollLifecycle:
    """Tests for poll lifecycle methods."""

    def test_on_poll_started_increments_count(self) -> None:
        """Test that on_poll_started increments poll count."""
        manager = SmartPollingManager(5)

        assert manager.poll_count_this_interval == 0

        manager.on_poll_started()
        assert manager.poll_count_this_interval == 1

        manager.on_poll_started()
        assert manager.poll_count_this_interval == 2

    def test_on_estimate_received_records_elapsed(self) -> None:
        """Test that on_estimate_received records elapsed time."""
        manager = SmartPollingManager(5)

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
        manager = SmartPollingManager(5)

        assert manager.has_confirmed_price is False

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)

            manager.on_confirmed_received()

        assert manager.has_confirmed_price is True


class TestForecastsPending:
    """Tests for forecasts pending state."""

    def test_set_forecasts_pending(self) -> None:
        """Test setting forecasts pending."""
        manager = SmartPollingManager(5)

        assert manager.forecasts_pending is False

        manager.set_forecasts_pending()
        assert manager.forecasts_pending is True

    def test_clear_forecasts_pending(self) -> None:
        """Test clearing forecasts pending."""
        manager = SmartPollingManager(5)

        manager.set_forecasts_pending()
        assert manager.forecasts_pending is True

        manager.clear_forecasts_pending()
        assert manager.forecasts_pending is False


class TestIntervalReset:
    """Tests for interval reset behavior."""

    def test_new_interval_resets_state(self) -> None:
        """Test that moving to a new interval resets all state."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            # Start first interval
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)
            manager.on_poll_started()
            manager.on_poll_started()
            manager.on_confirmed_received()
            manager.set_forecasts_pending()

            # Verify state is set
            assert manager.has_confirmed_price is True
            assert manager.forecasts_pending is True
            assert manager.poll_count_this_interval == 2

            # Move to next interval
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)

            # Verify state is reset
            assert manager.has_confirmed_price is False
            assert manager.forecasts_pending is False
            assert manager.poll_count_this_interval == 0

    def test_first_interval_flag_clears_on_second_interval(self) -> None:
        """Test that first_interval_after_startup clears on second interval."""
        manager = SmartPollingManager(5)

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
        manager = SmartPollingManager(5)

        stats = manager.get_cdf_stats()

        assert stats.observation_count == 100  # Cold start synthetic observations
        assert stats.confirmatory_poll_count == 0
        assert stats.scheduled_polls == [21.0, 27.0, 33.0, 39.0]


class TestPollingState:
    """Tests for PollingState dataclass."""

    def test_polling_state_fields(self) -> None:
        """Test PollingState dataclass fields."""
        state = PollingState(
            current_interval_start=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            has_confirmed_price=True,
            forecasts_pending=False,
            poll_count_this_interval=3,
            first_interval_after_startup=False,
            last_estimate_elapsed=10.5,
        )

        assert state.current_interval_start == datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert state.has_confirmed_price is True
        assert state.forecasts_pending is False
        assert state.poll_count_this_interval == 3
        assert state.first_interval_after_startup is False
        assert state.last_estimate_elapsed == 10.5


class TestRateLimitBasedPolling:
    """Tests for rate limit based k calculation."""

    def test_calculate_polls_equals_remaining(self) -> None:
        """Test k equals remaining from rate limit info."""
        manager = SmartPollingManager(5)

        result = manager._calculate_polls_per_interval({"remaining": 45})
        assert result == 45

        result = manager._calculate_polls_per_interval({"remaining": 5})
        assert result == 5

        result = manager._calculate_polls_per_interval({"remaining": 1})
        assert result == 1

    def test_should_poll_uses_rate_limit_info(self) -> None:
        """Test that should_poll uses rate limit info for k calculation."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # First poll with 45 remaining
            result = manager.should_poll(
                has_data=True,
                rate_limit_info={"remaining": 45},
            )
            assert result is True

            # Should have scheduled 45 polls (k = remaining)
            stats = manager.get_cdf_stats()
            assert len(stats.scheduled_polls) == 45

    def test_update_budget_dynamically_adjusts_schedule(self) -> None:
        """Test that update_budget dynamically adjusts the schedule mid-interval."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # Start interval with 45 remaining
            manager.should_poll(has_data=True, rate_limit_info={"remaining": 45})
            assert len(manager.get_cdf_stats().scheduled_polls) == 45

            # Time passes, budget shrinks to 10
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 15, tzinfo=UTC)
            manager.update_budget({"remaining": 10})

            # Schedule should now have 10 polls
            assert len(manager.get_cdf_stats().scheduled_polls) == 10


class TestGetNextPollDelay:
    """Tests for get_next_poll_delay method."""

    def test_get_next_poll_delay_when_confirmed(self) -> None:
        """Test delay returns None when confirmed price received."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)
            manager.on_confirmed_received()

            delay = manager.get_next_poll_delay()
            assert delay is None

    def test_get_next_poll_delay_no_interval(self) -> None:
        """Test delay returns None before interval starts."""
        manager = SmartPollingManager(5)

        # No interval started yet
        delay = manager.get_next_poll_delay()
        assert delay is None

    def test_get_next_poll_delay_returns_seconds(self) -> None:
        """Test delay returns seconds until next poll."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.should_poll(has_data=True)

            # At interval start, first poll is at 21s (cold start schedule)
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 5, tzinfo=UTC)
            delay = manager.get_next_poll_delay()
            assert delay is not None
            assert delay == 16.0  # 21 - 5


class TestObservationsProperty:
    """Tests for observations property."""

    def test_observations_returns_copy(self) -> None:
        """Test observations property returns a copy."""
        manager = SmartPollingManager(5)

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
        manager = SmartPollingManager(5)

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
        manager = SmartPollingManager(5)

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
        manager = SmartPollingManager(5)

        # Should not crash
        manager.update_budget({"remaining": 10})


class TestCheckNewInterval:
    """Tests for check_new_interval method."""

    def test_check_new_interval_first_call(self) -> None:
        """Test check_new_interval on first call."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            result = manager.check_new_interval(has_data=False)
            assert result is True

    def test_check_new_interval_same_interval(self) -> None:
        """Test check_new_interval returns False for same interval."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            manager.check_new_interval(has_data=True)

            # Same interval
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 2, 30, tzinfo=UTC)
            result = manager.check_new_interval(has_data=True)
            assert result is False

    def test_check_new_interval_with_rate_limit_info(self) -> None:
        """Test check_new_interval uses rate limit info for k."""
        manager = SmartPollingManager(5)

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            result = manager.check_new_interval(
                has_data=True,
                rate_limit_info={"remaining": 10},
            )
            assert result is True

            # Should have scheduled 10 polls
            stats = manager.get_cdf_stats()
            assert len(stats.scheduled_polls) == 10
