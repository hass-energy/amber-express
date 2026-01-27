"""Exponential backoff rate limiter for API calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

_LOGGER = logging.getLogger(__name__)


class ExponentialBackoffRateLimiter:
    """Manages exponential backoff for rate-limited API calls.

    This class tracks rate limit events and applies exponential backoff
    to prevent overwhelming the API.
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

    def record_rate_limit(self, reset_seconds: int | None = None) -> datetime:
        """Record a rate limit event and set backoff.

        If reset_seconds is provided (from API ratelimit-reset header), use that.
        Otherwise, fall back to exponential backoff.

        Args:
            reset_seconds: Seconds until quota resets (from API header)

        Returns:
            When the rate limit expires

        """
        if reset_seconds is not None and reset_seconds > 0:
            # Use the API-provided reset time (add small buffer)
            self._backoff_seconds = reset_seconds + 2
            _LOGGER.warning(
                "Rate limited (429). Waiting %d seconds (from API reset header)",
                self._backoff_seconds,
            )
        elif self._backoff_seconds == 0:
            self._backoff_seconds = self._initial_backoff
            _LOGGER.warning(
                "Rate limited (429). Backing off for %d seconds",
                self._backoff_seconds,
            )
        else:
            self._backoff_seconds = min(self._backoff_seconds * 2, self._max_backoff)
            _LOGGER.warning(
                "Rate limited (429). Backing off for %d seconds (exponential)",
                self._backoff_seconds,
            )

        self._rate_limit_until = datetime.now(UTC) + timedelta(seconds=self._backoff_seconds)

        return self._rate_limit_until

    @property
    def rate_limit_until(self) -> datetime | None:
        """Get when rate limit expires, or None if not limited."""
        return self._rate_limit_until

    @property
    def current_backoff(self) -> int:
        """Get the current backoff duration in seconds."""
        return self._backoff_seconds
