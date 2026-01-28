"""API client for Amber Electric API."""

from __future__ import annotations

import contextlib
from http import HTTPStatus
import logging
from typing import TYPE_CHECKING, TypeGuard

import amberelectric
from amberelectric.api import amber_api
from amberelectric.configuration import Configuration
from amberelectric.models import Site
from amberelectric.models.interval import Interval
from amberelectric.rest import ApiException
import http_sf

from .rate_limiter import ExponentialBackoffRateLimiter
from .types import RateLimitInfo

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# HTTP status codes
HTTP_TOO_MANY_REQUESTS = 429


# =============================================================================
# Exceptions
# =============================================================================


class AmberApiError(Exception):
    """Raised when the Amber API returns an error."""

    def __init__(self, message: str, status: int) -> None:
        """Initialize with message and HTTP status code."""
        super().__init__(message)
        self.status = status


class RateLimitedError(AmberApiError):
    """Raised when the API rate limit is exceeded."""

    def __init__(self, reset_seconds: int | None = None) -> None:
        """Initialize with optional reset time in seconds."""
        super().__init__("Rate limited by Amber API", HTTP_TOO_MANY_REQUESTS)
        self.reset_seconds = reset_seconds


# =============================================================================
# TypeGuards
# =============================================================================


def _is_site_list(data: object) -> TypeGuard[list[Site]]:
    """Validate data is a list of Site objects."""
    return isinstance(data, list) and all(isinstance(site, Site) for site in data)


def _is_interval_list(data: object) -> TypeGuard[list[Interval]]:
    """Validate data is a list of Interval objects."""
    return isinstance(data, list) and all(isinstance(item, Interval) for item in data)


class AmberApiClient:
    """Handles all HTTP communication with the Amber Electric API.

    Responsibilities:
    - Making HTTP requests to the Amber API (fetch_sites, fetch_current_prices)
    - Parsing IETF RateLimit headers from API responses
    - Recording rate limit events and triggering backoff via the rate limiter
    - Tracking last API status code for error reporting
    - Returning raw API data (Site objects, Interval lists) for processing elsewhere

    This class is intentionally "dumb" about business logic - it doesn't know about
    polling strategies, data processing, or Home Assistant entities. It only knows
    how to talk to the API and handle HTTP-level concerns.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_token: str,
        rate_limiter: ExponentialBackoffRateLimiter,
    ) -> None:
        """Initialize the API client.

        Args:
            hass: Home Assistant instance (for async executor)
            api_token: Amber API token
            rate_limiter: Rate limiter for backoff handling

        """
        self._hass = hass
        self._rate_limiter = rate_limiter

        # API client
        configuration = Configuration(access_token=api_token)
        self._api = amber_api.AmberApi(amberelectric.ApiClient(configuration))

        # API status tracking
        self._last_api_status: int = HTTPStatus.OK
        self._rate_limit_info: RateLimitInfo = {}

    @property
    def last_status(self) -> int:
        """Get last API status code (200 = OK)."""
        return self._last_api_status

    @property
    def rate_limit_info(self) -> RateLimitInfo:
        """Get rate limit information from last API response."""
        return self._rate_limit_info

    async def fetch_sites(self) -> list[Site]:
        """Fetch all sites for this API token.

        Returns:
            List of Site objects.

        Raises:
            RateLimitedError: If rate limited by the API.
            AmberApiError: If the API returns an error.

        """
        try:
            response = await self._hass.async_add_executor_job(self._api.get_sites_with_http_info)
            self._parse_rate_limit_headers(response.headers)
            self._last_api_status = HTTPStatus.OK
            if not _is_site_list(response.data):
                msg = "Unexpected response format from get_sites"
                raise AmberApiError(msg, HTTPStatus.INTERNAL_SERVER_ERROR)
            return response.data
        except ApiException as err:
            status = err.status or HTTPStatus.INTERNAL_SERVER_ERROR
            self._last_api_status = status

            if err.status == HTTP_TOO_MANY_REQUESTS:
                reset_seconds = self._get_reset_from_error(err)
                self._rate_limiter.record_rate_limit(reset_seconds)
                raise RateLimitedError(reset_seconds) from err

            msg = f"Failed to fetch sites: {err}"
            raise AmberApiError(msg, status) from err

    async def fetch_current_prices(
        self,
        site_id: str,
        *,
        next_intervals: int = 0,
        resolution: int = 30,
    ) -> list[Interval]:
        """Fetch current prices and optionally forecasts.

        Args:
            site_id: The site ID to fetch prices for
            next_intervals: Number of forecast intervals to include
            resolution: Interval resolution in minutes (5 or 30)

        Returns:
            List of Interval objects.

        Raises:
            RateLimitedError: If rate limited by the API.
            AmberApiError: If the API returns an error.

        """
        # Check if we're in a rate limit backoff period
        if self._rate_limiter.is_limited():
            remaining = self._rate_limiter.remaining_seconds()
            _LOGGER.debug("Rate limit backoff: %.0f seconds remaining", remaining)
            raise RateLimitedError

        try:
            response = await self._hass.async_add_executor_job(
                lambda: self._api.get_current_prices_with_http_info(
                    site_id,
                    next=next_intervals,
                    previous=0,
                    resolution=resolution,
                )
            )
            self._parse_rate_limit_headers(response.headers)
            self._rate_limiter.record_success()
            self._last_api_status = HTTPStatus.OK

            if not _is_interval_list(response.data):
                msg = "Unexpected response format from get_current_prices"
                raise AmberApiError(msg, HTTPStatus.INTERNAL_SERVER_ERROR)

            return response.data
        except ApiException as err:
            status = err.status or HTTPStatus.INTERNAL_SERVER_ERROR
            self._last_api_status = status

            if err.status == HTTP_TOO_MANY_REQUESTS:
                reset_seconds = self._get_reset_from_error(err)
                self._rate_limiter.record_rate_limit(reset_seconds)
                raise RateLimitedError(reset_seconds) from err

            msg = f"Amber API error ({status}): {err.reason}"
            raise AmberApiError(msg, status) from err

    def _parse_rate_limit_headers(self, headers: dict[str, str] | None) -> None:
        """Parse IETF RateLimit headers from API response.

        See: https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/
        """
        if not headers:
            return

        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Parse ratelimit-policy using RFC 8941 structured fields (e.g., "50;w=300")
        policy = headers_lower.get("ratelimit-policy")
        limit: int | None = None
        window: int | None = None

        if policy:
            try:
                result = http_sf.parse(policy.encode(), tltype="item")
                if isinstance(result, tuple) and len(result) == 2:  # noqa: PLR2004
                    value, params = result
                    if isinstance(value, int):
                        limit = value
                    w = params.get("w")
                    if isinstance(w, int):
                        window = w
            except http_sf.StructuredFieldError:
                _LOGGER.debug("Failed to parse RateLimit-Policy header: %s", policy)

        # Parse individual headers
        remaining: int | None = None
        reset: int | None = None

        if "ratelimit-remaining" in headers_lower:
            with contextlib.suppress(ValueError):
                remaining = int(headers_lower["ratelimit-remaining"])

        if "ratelimit-reset" in headers_lower:
            with contextlib.suppress(ValueError):
                reset = int(headers_lower["ratelimit-reset"])

        # Also check ratelimit-limit header (may override policy)
        if "ratelimit-limit" in headers_lower:
            with contextlib.suppress(ValueError):
                limit = int(headers_lower["ratelimit-limit"])

        self._rate_limit_info = {
            "limit": limit,
            "remaining": remaining,
            "reset_seconds": reset,
            "window_seconds": window,
            "policy": policy,
        }

    def _get_reset_from_error(self, err: ApiException) -> int:
        """Extract reset_seconds from ApiException headers."""
        headers = err.headers
        if headers is None:
            msg = "Rate limit response missing headers"
            raise ValueError(msg)
        return int(headers["ratelimit-reset"])
