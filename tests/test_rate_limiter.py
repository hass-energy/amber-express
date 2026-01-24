"""Tests for the exponential backoff rate limiter."""

from datetime import UTC, datetime
from unittest.mock import patch

from custom_components.amber_express.rate_limiter import ExponentialBackoffRateLimiter


class TestRateLimiterInit:
    """Tests for ExponentialBackoffRateLimiter initialization."""

    def test_default_values(self) -> None:
        """Test default initialization values."""
        limiter = ExponentialBackoffRateLimiter()

        assert limiter.current_backoff == 0
        assert limiter.rate_limit_until is None
        assert limiter.is_limited() is False

    def test_custom_values(self) -> None:
        """Test custom initialization values."""
        limiter = ExponentialBackoffRateLimiter(initial_backoff=5, max_backoff=60)

        # First rate limit should use custom initial
        limiter.record_rate_limit()
        assert limiter.current_backoff == 5


class TestIsLimited:
    """Tests for is_limited method."""

    def test_not_limited_when_no_rate_limit(self) -> None:
        """Test is_limited returns False when not rate limited."""
        limiter = ExponentialBackoffRateLimiter()

        assert limiter.is_limited() is False

    def test_limited_when_rate_limit_active(self) -> None:
        """Test is_limited returns True when rate limit is active."""
        limiter = ExponentialBackoffRateLimiter()

        with patch("custom_components.amber_express.rate_limiter.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            limiter.record_rate_limit()

            # Still at 10:00, limit until 10:00:10
            assert limiter.is_limited() is True

    def test_not_limited_when_rate_limit_expired(self) -> None:
        """Test is_limited returns False when rate limit has expired."""
        limiter = ExponentialBackoffRateLimiter()

        with patch("custom_components.amber_express.rate_limiter.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            limiter.record_rate_limit()

            # Move past the limit
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 15, tzinfo=UTC)
            assert limiter.is_limited() is False


class TestRemainingSeconds:
    """Tests for remaining_seconds method."""

    def test_zero_when_not_limited(self) -> None:
        """Test remaining_seconds returns 0 when not rate limited."""
        limiter = ExponentialBackoffRateLimiter()

        assert limiter.remaining_seconds() == 0

    def test_correct_remaining_time(self) -> None:
        """Test remaining_seconds returns correct time remaining."""
        limiter = ExponentialBackoffRateLimiter()

        # Record a rate limit
        limiter.record_rate_limit()

        # Remaining should be approximately the initial backoff (10s)
        remaining = limiter.remaining_seconds()
        assert 9 <= remaining <= 10  # Allow for test execution time

    def test_zero_when_expired(self) -> None:
        """Test remaining_seconds returns 0 when limit has expired."""
        limiter = ExponentialBackoffRateLimiter()

        with patch("custom_components.amber_express.rate_limiter.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            limiter.record_rate_limit()

            # Move past the limit
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 15, tzinfo=UTC)
            remaining = limiter.remaining_seconds()
            assert remaining == 0


class TestRecordSuccess:
    """Tests for record_success method."""

    def test_resets_backoff(self) -> None:
        """Test record_success resets backoff to 0."""
        limiter = ExponentialBackoffRateLimiter()

        # Set up a rate limit
        limiter.record_rate_limit()
        assert limiter.current_backoff == 10

        limiter.record_success()
        assert limiter.current_backoff == 0

    def test_clears_rate_limit_until(self) -> None:
        """Test record_success clears rate_limit_until."""
        limiter = ExponentialBackoffRateLimiter()

        limiter.record_rate_limit()
        assert limiter.rate_limit_until is not None

        limiter.record_success()
        assert limiter.rate_limit_until is None

    def test_clears_limited_state(self) -> None:
        """Test record_success clears limited state."""
        limiter = ExponentialBackoffRateLimiter()

        with patch("custom_components.amber_express.rate_limiter.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            limiter.record_rate_limit()
            assert limiter.is_limited() is True

            limiter.record_success()
            assert limiter.is_limited() is False


class TestRecordRateLimit:
    """Tests for record_rate_limit method."""

    def test_first_rate_limit_uses_initial_backoff(self) -> None:
        """Test first rate limit uses initial backoff value."""
        limiter = ExponentialBackoffRateLimiter(initial_backoff=10)

        limiter.record_rate_limit()

        assert limiter.current_backoff == 10

    def test_exponential_backoff_doubles(self) -> None:
        """Test exponential backoff doubles on each rate limit."""
        limiter = ExponentialBackoffRateLimiter(initial_backoff=10, max_backoff=300)

        limiter.record_rate_limit()
        assert limiter.current_backoff == 10

        # Clear rate limit so we can trigger another
        limiter._rate_limit_until = None

        limiter.record_rate_limit()
        assert limiter.current_backoff == 20

        limiter._rate_limit_until = None

        limiter.record_rate_limit()
        assert limiter.current_backoff == 40

    def test_backoff_respects_max(self) -> None:
        """Test backoff does not exceed max_backoff."""
        limiter = ExponentialBackoffRateLimiter(initial_backoff=100, max_backoff=150)

        limiter.record_rate_limit()
        assert limiter.current_backoff == 100

        limiter._rate_limit_until = None
        limiter.record_rate_limit()
        assert limiter.current_backoff == 150  # Would be 200, but capped

        limiter._rate_limit_until = None
        limiter.record_rate_limit()
        assert limiter.current_backoff == 150  # Still capped

    def test_returns_expiry_time(self) -> None:
        """Test record_rate_limit returns expiry datetime."""
        limiter = ExponentialBackoffRateLimiter(initial_backoff=10)

        expiry = limiter.record_rate_limit()

        # Returned value should match the property
        assert expiry == limiter.rate_limit_until
        assert expiry is not None

    def test_sets_rate_limit_until(self) -> None:
        """Test record_rate_limit sets rate_limit_until."""
        limiter = ExponentialBackoffRateLimiter()

        assert limiter.rate_limit_until is None

        limiter.record_rate_limit()

        assert limiter.rate_limit_until is not None


class TestBackoffSequence:
    """Tests for complete backoff sequences."""

    def test_full_backoff_sequence(self) -> None:
        """Test a full sequence of rate limits and success."""
        limiter = ExponentialBackoffRateLimiter(initial_backoff=10, max_backoff=80)

        # First rate limit
        limiter.record_rate_limit()
        assert limiter.current_backoff == 10

        # Success resets
        limiter.record_success()
        assert limiter.current_backoff == 0
        assert limiter.rate_limit_until is None

        # Start over
        limiter.record_rate_limit()
        assert limiter.current_backoff == 10

        # Multiple consecutive rate limits
        limiter._rate_limit_until = None
        limiter.record_rate_limit()
        assert limiter.current_backoff == 20

        limiter._rate_limit_until = None
        limiter.record_rate_limit()
        assert limiter.current_backoff == 40

        limiter._rate_limit_until = None
        limiter.record_rate_limit()
        assert limiter.current_backoff == 80  # Capped

        limiter._rate_limit_until = None
        limiter.record_rate_limit()
        assert limiter.current_backoff == 80  # Still capped


class TestProperties:
    """Tests for rate limiter properties."""

    def test_rate_limit_until_property(self) -> None:
        """Test rate_limit_until property."""
        limiter = ExponentialBackoffRateLimiter()

        assert limiter.rate_limit_until is None

        limiter.record_rate_limit()
        assert limiter.rate_limit_until is not None
        assert isinstance(limiter.rate_limit_until, datetime)

    def test_current_backoff_property(self) -> None:
        """Test current_backoff property."""
        limiter = ExponentialBackoffRateLimiter(initial_backoff=15)

        assert limiter.current_backoff == 0

        limiter.record_rate_limit()
        assert limiter.current_backoff == 15
