"""API client for Amber Electric API."""

from __future__ import annotations

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from http import HTTPStatus
import logging
import os
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

    def __init__(self, reset_at: datetime | None = None) -> None:
        """Initialize with optional reset time."""
        super().__init__("Rate limited by Amber API", HTTP_TOO_MANY_REQUESTS)
        self.reset_at = reset_at


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
            # API always returns rate limit headers
            headers = response.headers or {}
            self._rate_limit_info = self._extract_rate_limit_info(headers)
            self._last_api_status = HTTPStatus.OK
            if not _is_site_list(response.data):
                msg = "Unexpected response format from get_sites"
                raise AmberApiError(msg, HTTPStatus.INTERNAL_SERVER_ERROR)

            # Debug: Override interval length for testing different site configurations
            if override := os.environ.get("AMBER_OVERRIDE_INTERVAL"):
                for site in response.data:
                    site.interval_length = int(override)

            return response.data
        except ApiException as err:
            status = err.status or HTTPStatus.INTERNAL_SERVER_ERROR
            self._last_api_status = status

            if err.status == HTTP_TOO_MANY_REQUESTS:
                reset_at = self._extract_reset_at_from_429(err.headers)
                self._rate_limiter.record_rate_limit(reset_at)
                raise RateLimitedError(reset_at) from err

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

        # Debug: Override resolution for testing different site configurations
        if override := os.environ.get("AMBER_OVERRIDE_INTERVAL"):
            resolution = int(override)

        try:
            response = await self._hass.async_add_executor_job(
                lambda: self._api.get_current_prices_with_http_info(
                    site_id,
                    next=next_intervals,
                    previous=0,
                    resolution=resolution,
                )
            )
            # API always returns rate limit headers
            headers = response.headers or {}
            self._rate_limit_info = self._extract_rate_limit_info(headers)
            self._rate_limiter.record_success()
            self._last_api_status = HTTPStatus.OK

            if not _is_interval_list(response.data):
                msg = "Unexpected response format from get_current_prices"
                raise AmberApiError(msg, HTTPStatus.INTERNAL_SERVER_ERROR)

            # Debug: Force all prices to be estimates for testing CDF polling
            if os.environ.get("AMBER_FORCE_ESTIMATES"):
                for interval in response.data:
                    inner = interval.actual_instance
                    if hasattr(inner, "estimate"):
                        inner.__dict__["estimate"] = True

            return response.data
        except ApiException as err:
            status = err.status or HTTPStatus.INTERNAL_SERVER_ERROR
            self._last_api_status = status

            if err.status == HTTP_TOO_MANY_REQUESTS:
                reset_at = self._extract_reset_at_from_429(err.headers)
                self._rate_limiter.record_rate_limit(reset_at)
                raise RateLimitedError(reset_at) from err

            msg = f"Amber API error ({status}): {err.reason}"
            raise AmberApiError(msg, status) from err

    def _extract_reset_at_from_429(self, headers: dict[str, str] | None) -> datetime | None:
        """Extract reset time from 429 response headers, with fallback.

        Returns None if headers are missing or invalid, triggering exponential backoff.
        """
        if not headers:
            _LOGGER.debug("429 response missing headers, using exponential backoff")
            return None

        try:
            self._rate_limit_info = self._extract_rate_limit_info(headers)
            return self._rate_limit_info["reset_at"]
        except (KeyError, ValueError) as err:
            _LOGGER.debug(
                "429 response missing rate limit headers (%s), using exponential backoff",
                err,
            )
            return None

    def _extract_rate_limit_info(self, headers: dict[str, str]) -> RateLimitInfo:
        """Extract rate limit info from IETF RateLimit headers.

        See: https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/

        Raises:
            KeyError: If required headers are missing.
            ValueError: If header values are invalid.

        """
        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Parse ratelimit-policy using RFC 8941 structured fields (e.g., "50;w=300")
        policy = headers_lower["ratelimit-policy"]
        parsed = http_sf.parse(policy.encode(), tltype="item")
        # Result is (value, params) tuple where value is int and params is dict
        value: int = parsed[0]  # type: ignore[assignment,index]
        params: dict[str, int] = parsed[1]  # type: ignore[assignment,index]
        limit = value
        window = params["w"]

        # ratelimit-limit header may override policy limit
        if "ratelimit-limit" in headers_lower:
            limit = int(headers_lower["ratelimit-limit"])

        reset_seconds = int(headers_lower["ratelimit-reset"])
        # Use server timestamp from Date header for accurate reset time calculation
        server_time = parsedate_to_datetime(headers_lower["date"])
        reset_at = server_time + timedelta(seconds=reset_seconds)

        return {
            "limit": limit,
            "remaining": int(headers_lower["ratelimit-remaining"]),
            "reset_seconds": reset_seconds,
            "reset_at": reset_at,
            "window_seconds": window,
            "policy": policy,
        }
