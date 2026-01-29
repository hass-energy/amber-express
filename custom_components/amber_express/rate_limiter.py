"""Exponential backoff rate limiter for API calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

_LOGGER = logging.getLogger(__name__)


class ExponentialBackoffRateLimiter:
    """Manages exponential backoff for rate-limited API calls.

    Responsibilities:
    - Tracking whether we're currently in a rate-limit backoff period
    - Recording rate limit events (429 responses) and calculating backoff duration
    - Using API-provided reset time when available, falling back to exponential backoff
    - Resetting backoff on successful API calls
    - Providing remaining seconds until rate limit expires

    The backoff strategy:
    1. If API provides ratelimit-reset header, use that duration + 2s buffer
    2. Otherwise, start at initial_backoff (10s) and double on each consecutive 429
    3. Cap at max_backoff (300s / 5 minutes)
    4. Reset to 0 on any successful API call

    This class is shared between AmberApiClient (which records events) and the
    coordinator (which checks before scheduling polls).
    """

    def __init__(
        self,
        *,
        initial_backoff: int = 10,
        max_backoff: int = 300,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            initial_backoff: Initial backoff duration in seconds
            max_backoff: Maximum backoff duration in seconds

        """
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._backoff_seconds = 0
        self._rate_limit_until: datetime | None = None

    def is_limited(self) -> bool:
        """Check if we're currently rate limited.

        Returns:
            True if rate limited, False otherwise

        """
        if self._rate_limit_until is None:
            return False
        return datetime.now(UTC) < self._rate_limit_until

    def remaining_seconds(self) -> float:
        """Get remaining seconds until rate limit expires.

        Returns:
            Seconds remaining, or 0 if not rate limited

        """
        if self._rate_limit_until is None:
            return 0
        remaining = (self._rate_limit_until - datetime.now(UTC)).total_seconds()
        return max(0, remaining)

    def record_success(self) -> None:
        """Record a successful API call, resetting backoff."""
        self._backoff_seconds = 0
        self._rate_limit_until = None

    def record_rate_limit(self, reset_at: datetime | None) -> datetime:
        """Record a rate limit event and set backoff.

        Uses reset_at from API header if provided, otherwise falls back
        to exponential backoff.

        Args:
            reset_at: When quota resets (from API header), or None to use backoff

        Returns:
            When the rate limit expires

        """
        now = datetime.now(UTC)

        if reset_at is not None:
            # Use the API-provided reset time (add small buffer)
            self._backoff_seconds = int((reset_at - now).total_seconds()) + 2
            self._rate_limit_until = reset_at + timedelta(seconds=2)
            _LOGGER.warning(
                "Rate limited (429). Waiting until %s (from API reset header)",
                self._rate_limit_until.strftime("%H:%M:%S"),
            )
        elif self._backoff_seconds == 0:
            self._backoff_seconds = self._initial_backoff
            self._rate_limit_until = now + timedelta(seconds=self._backoff_seconds)
            _LOGGER.warning(
                "Rate limited (429). Backing off for %d seconds",
                self._backoff_seconds,
            )
        else:
            self._backoff_seconds = min(self._backoff_seconds * 2, self._max_backoff)
            self._rate_limit_until = now + timedelta(seconds=self._backoff_seconds)
            _LOGGER.warning(
                "Rate limited (429). Backing off for %d seconds (exponential)",
                self._backoff_seconds,
            )

        return self._rate_limit_until

    @property
    def rate_limit_until(self) -> datetime | None:
        """Get when rate limit expires, or None if not limited."""
        return self._rate_limit_until

    @property
    def current_backoff(self) -> int:
        """Get the current backoff duration in seconds."""
        return self._backoff_seconds
