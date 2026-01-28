"""API client for Amber Electric API."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from http import HTTPStatus
import logging
from typing import TYPE_CHECKING, Any

import amberelectric
from amberelectric.api import amber_api
from amberelectric.configuration import Configuration
from amberelectric.rest import ApiException
import http_sf

from .rate_limiter import ExponentialBackoffRateLimiter
from .types import RateLimitInfo

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# HTTP status codes
HTTP_TOO_MANY_REQUESTS = 429


@dataclass
class FetchResult:
    """Result of fetching prices from the API."""

    intervals: list[Any] | None
    status: int
    rate_limited: bool = False


class AmberApiClient:
    """Client for communicating with the Amber Electric API.

    Handles all HTTP communication, rate limit header parsing,
    and error handling. Returns raw API data for processing elsewhere.
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

    async def fetch_sites(self) -> list[Any] | None:
        """Fetch all sites for this API token.

        Returns:
            List of Site objects, or None on error.

        """
        try:
            response = await self._hass.async_add_executor_job(self._api.get_sites_with_http_info)
            self._parse_rate_limit_headers(response.headers)
            self._last_api_status = HTTPStatus.OK
            return response.data if response.data else []
        except ApiException as err:
            if err.status == HTTP_TOO_MANY_REQUESTS:
                reset_seconds = self._get_reset_from_error(err)
                self._rate_limiter.record_rate_limit(reset_seconds)
                self._last_api_status = HTTP_TOO_MANY_REQUESTS
            else:
                self._last_api_status = err.status or HTTPStatus.INTERNAL_SERVER_ERROR
                _LOGGER.warning("Failed to fetch sites: %s", err)
            return None
        except Exception as err:
            _LOGGER.warning("Failed to fetch sites: %s", err)
            return None

    async def fetch_current_prices(
        self,
        site_id: str,
        *,
        next_intervals: int = 0,
        resolution: int = 30,
    ) -> FetchResult:
        """Fetch current prices and optionally forecasts.

        Args:
            site_id: The site ID to fetch prices for
            next_intervals: Number of forecast intervals to include
            resolution: Interval resolution in minutes (5 or 30)

        Returns:
            FetchResult with intervals, status, and rate limit flag

        """
        # Check if we're in a rate limit backoff period
        if self._rate_limiter.is_limited():
            remaining = self._rate_limiter.remaining_seconds()
            _LOGGER.debug("Rate limit backoff: %.0f seconds remaining", remaining)
            return FetchResult(intervals=None, status=HTTP_TOO_MANY_REQUESTS, rate_limited=True)

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

            return FetchResult(
                intervals=response.data,
                status=HTTPStatus.OK,
            )
        except ApiException as err:
            status = err.status or HTTPStatus.INTERNAL_SERVER_ERROR
            self._last_api_status = status

            if err.status == HTTP_TOO_MANY_REQUESTS:
                reset_seconds = self._get_reset_from_error(err)
                self._rate_limiter.record_rate_limit(reset_seconds)
                return FetchResult(intervals=None, status=status, rate_limited=True)

            _LOGGER.warning("Amber API error (%d): %s", status, err.reason)
            return FetchResult(intervals=None, status=status)
        except Exception as err:
            _LOGGER.warning("Failed to fetch Amber data: %s", err)
            return FetchResult(intervals=None, status=HTTPStatus.INTERNAL_SERVER_ERROR)

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

    def _get_reset_from_error(self, err: ApiException) -> int | None:
        """Extract reset_seconds from ApiException headers."""
        if not err.headers:
            return None
        reset_str = err.headers.get("ratelimit-reset")
        if reset_str:
            with contextlib.suppress(ValueError):
                return int(reset_str)
        return None
