"""Data coordinator for Amber Express integration."""

from __future__ import annotations

import contextlib
from http import HTTPStatus
import logging
from typing import Any

import amberelectric
from amberelectric.api import amber_api
from amberelectric.configuration import Configuration
from amberelectric.rest import ApiException
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_DEMAND_WINDOW,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_TARIFF_BLOCK,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_API_TOKEN,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_WAIT_FOR_CONFIRMED,
    DATA_SOURCE_POLLING,
    DEFAULT_PRICING_MODE,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
    FORECAST_INTERVALS,
)
from .data_source import DataSourceMerger
from .interval_processor import IntervalProcessor
from .polling_offset import PollingOffsetStats
from .rate_limiter import ExponentialBackoffRateLimiter
from .smart_polling import SmartPollingManager
from .types import ChannelData, ChannelInfo, CoordinatorData, RateLimitInfo, SiteInfoData, TariffInfoData

_LOGGER = logging.getLogger(__name__)

# HTTP status codes
HTTP_TOO_MANY_REQUESTS = 429


class AmberDataCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinator for Amber Express data.

    Each coordinator is responsible for a single site (subentry).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            entry: Main config entry (contains API token).
            subentry: Site subentry (contains site-specific config).

        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{subentry.subentry_id}",
            update_interval=None,  # Polling is handled by async_track_time_change for clock alignment
        )
        self.entry = entry
        self.subentry = subentry
        self.subentry_id = subentry.subentry_id

        # Extract config from entry and subentry
        self.api_token = entry.data[CONF_API_TOKEN]
        self.site_id = subentry.data[CONF_SITE_ID]

        # API client
        configuration = Configuration(access_token=self.api_token)
        self._api = amber_api.AmberApi(amberelectric.ApiClient(configuration))

        # Interval processor for transforming API responses
        pricing_mode = self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)
        self._interval_processor = IntervalProcessor(pricing_mode)

        # Smart polling manager
        self._polling_manager = SmartPollingManager()

        # Exponential backoff for 429 errors
        self._rate_limiter = ExponentialBackoffRateLimiter()

        # Data source merger for combining polling and websocket data
        self._data_sources = DataSourceMerger()

        # Site info (from subentry or fetched at startup)
        self._site_info: SiteInfoData = self._build_site_info_from_subentry()
        self._site_info_fetched = False

        # Merged data (exposed via data_sources)
        self.current_data: CoordinatorData = {}
        self.data_source: str = DATA_SOURCE_POLLING

        # API status tracking (OK = 200, error codes otherwise)
        self._last_api_status: int = HTTPStatus.OK

        # Rate limit info from API response headers
        self._rate_limit_info: RateLimitInfo = {}

    def _get_subentry_option(self, key: str, default: Any) -> Any:
        """Get an option from subentry data."""
        return self.subentry.data.get(key, default)

    def update_pricing_mode(self, new_mode: str) -> None:
        """Update the pricing mode and recreate the interval processor."""
        self._interval_processor = IntervalProcessor(new_mode)

    def _build_site_info_from_subentry(self) -> SiteInfoData:
        """Build initial site info from subentry data."""
        data = self.subentry.data
        channels_raw = data.get("channels", [])
        channels: list[ChannelInfo] = [
            {
                "identifier": ch.get("identifier"),
                "type": ch.get("type", ""),
                "tariff": ch.get("tariff"),
            }
            for ch in channels_raw
            if isinstance(ch, dict)
        ]
        return {
            "id": data.get(CONF_SITE_ID, ""),
            "nmi": data.get("nmi", ""),
            "network": data.get("network"),
            "status": "active",
            "channels": channels,
        }

    def should_poll(self) -> bool:
        """Check if polling is needed (public interface for __init__.py)."""
        return self._polling_manager.should_poll(
            has_data=bool(self.current_data),
            rate_limit_until=self._rate_limiter.rate_limit_until,
        )

    async def _async_update_data(self) -> CoordinatorData:
        """Fetch data from Amber API using smart polling."""
        # Fetch site info on first run (for tariff codes etc.)
        if not self._site_info_fetched:
            try:
                await self._fetch_site_info()
            except Exception as err:
                _LOGGER.warning("Failed to fetch site info: %s", err)
            self._site_info_fetched = True

        try:
            await self._fetch_amber_data()
        except amberelectric.ApiException as err:
            msg = f"Error communicating with Amber API: {err}"
            raise UpdateFailed(msg) from err
        except Exception as err:
            msg = f"Unexpected error: {err}"
            raise UpdateFailed(msg) from err

        # Merge data from polling and websocket
        self._update_from_sources()

        return self.current_data

    async def _fetch_site_info(self) -> None:
        """Fetch site information including channels and tariff codes."""
        _LOGGER.debug("Fetching site info for site %s", self.site_id)

        try:
            response = await self.hass.async_add_executor_job(self._api.get_sites_with_http_info)
            # Parse rate limit headers from successful response
            self._parse_rate_limit_headers(response.headers)
            sites = response.data if response.data else []
        except ApiException as err:
            if err.status == HTTP_TOO_MANY_REQUESTS:
                reset_seconds = self._get_reset_from_error(err)
                self._rate_limiter.record_rate_limit(reset_seconds)
            else:
                _LOGGER.warning("Failed to fetch sites: %s", err)
            return
        except Exception as err:
            _LOGGER.warning("Failed to fetch sites: %s", err)
            return

        # Find our site
        for site in sites:
            if site.id == self.site_id:
                # Extract channel info including tariff codes
                channels_info: list[ChannelInfo] = []
                for ch in site.channels or []:
                    channel_type = ch.type.value if hasattr(ch.type, "value") else str(ch.type)
                    channel_info: ChannelInfo = {
                        "identifier": getattr(ch, "identifier", None),
                        "type": channel_type,
                        "tariff": getattr(ch, "tariff", None),
                    }
                    channels_info.append(channel_info)

                self._site_info = {
                    "id": site.id,
                    "nmi": site.nmi,
                    "network": getattr(site, "network", None),
                    "status": site.status.value if hasattr(site.status, "value") else str(site.status),
                    "channels": channels_info,
                    "active_from": getattr(site, "active_from", None),
                    "interval_length": getattr(site, "interval_length", None),
                }
                _LOGGER.debug("Fetched site info: %s", self._site_info)
                return

        _LOGGER.warning("Site %s not found in API response", self.site_id)

    async def _fetch_amber_data(self) -> None:
        """Fetch current prices and forecasts from Amber API."""
        # Check if we're in a rate limit backoff period
        if self._rate_limiter.is_limited():
            remaining = self._rate_limiter.remaining_seconds()
            _LOGGER.debug("Rate limit backoff: %.0f seconds remaining", remaining)
            return

        # Use site's interval_length for resolution (default to 30 if not available)
        interval_length = self._site_info.get("interval_length")
        resolution = int(interval_length) if interval_length is not None else 30

        # Skip if we already have confirmed price for this interval
        if self._polling_manager.has_confirmed_price and not self._polling_manager.forecasts_pending:
            return

        # If we have confirmed price but forecasts are pending, only fetch forecasts
        if self._polling_manager.has_confirmed_price and self._polling_manager.forecasts_pending:
            _LOGGER.debug("Retrying forecast fetch...")
            forecasts_fetched = await self._fetch_forecasts(resolution)
            if forecasts_fetched:
                self._polling_manager.clear_forecasts_pending()
                self._data_sources.update_polling(forecasts_fetched)
                self._update_from_sources()
                self.async_set_updated_data(self.current_data)
                _LOGGER.info("Forecasts fetched successfully on retry")
            return

        # Record poll started
        self._polling_manager.on_poll_started()
        is_first_poll = self._polling_manager.poll_count_this_interval == 1

        _LOGGER.debug(
            "Polling Amber API (poll #%d for this interval)",
            self._polling_manager.poll_count_this_interval,
        )

        # First poll of interval: fetch with forecasts to ensure we have them immediately
        # Subsequent polls: fetch without forecasts (just checking for confirmed)
        next_intervals = FORECAST_INTERVALS if is_first_poll else 0

        try:
            response = await self.hass.async_add_executor_job(
                lambda: self._api.get_current_prices_with_http_info(
                    self.site_id,
                    next=next_intervals,
                    previous=0,
                    resolution=resolution,
                )
            )
            # Parse rate limit headers from successful response
            self._parse_rate_limit_headers(response.headers)
            # Reset backoff and record success
            self._rate_limiter.record_success()
            self._set_api_status(HTTPStatus.OK)

            if response.data is None:
                _LOGGER.debug("API returned no data")
                return
            intervals = response.data
        except ApiException as err:
            if err.status is not None:
                self._set_api_status(err.status)
                if err.status == HTTP_TOO_MANY_REQUESTS:
                    # Parse reset_seconds from error response headers
                    reset_seconds = self._get_reset_from_error(err)
                    self._rate_limiter.record_rate_limit(reset_seconds)
                else:
                    _LOGGER.warning("Amber API error (%d): %s", err.status, err.reason)
            else:
                _LOGGER.warning("Amber API error: %s", err.reason)
            return
        except Exception as err:
            _LOGGER.warning("Failed to fetch Amber data: %s", err)
            return

        # Process the intervals
        data = self._interval_processor.process_intervals(intervals)
        general_data = data.get(CHANNEL_GENERAL, {})

        if not general_data:
            _LOGGER.debug(
                "Poll %d: No data returned",
                self._polling_manager.poll_count_this_interval,
            )
            return

        # Log using centralized format
        self._log_price_data(data, f"Poll #{self._polling_manager.poll_count_this_interval}")

        is_estimate = general_data.get(ATTR_ESTIMATE, True)
        wait_for_confirmed = self._get_subentry_option(CONF_WAIT_FOR_CONFIRMED, DEFAULT_WAIT_FOR_CONFIRMED)

        # Confirmed price: update and stop polling
        if is_estimate is False:
            # Record confirmed price for offset tracking
            self._polling_manager.on_confirmed_received()

            # If not first poll, we need to fetch forecasts separately
            if not is_first_poll:
                forecasts_fetched = await self._fetch_forecasts(resolution)
                if not forecasts_fetched:
                    self._polling_manager.set_forecasts_pending()
                else:
                    self._polling_manager.clear_forecasts_pending()
                    data = forecasts_fetched

            self._data_sources.update_polling(data)
            _LOGGER.info("Confirmed price received, stopping polling for this interval")
        # Estimated price: only update on first poll (which has forecasts)
        else:
            # Track when we got this estimate for offset calculation
            self._polling_manager.on_estimate_received()

            # Only update on first poll - subsequent estimates are ignored to preserve forecasts
            if is_first_poll and not wait_for_confirmed:
                self._data_sources.update_polling(data)
                _LOGGER.debug("First poll estimate received with forecasts, updating sensors")
            elif is_first_poll:
                _LOGGER.debug("First poll estimate received, waiting for confirmed")
            else:
                _LOGGER.debug("Subsequent estimate ignored (preserving forecasts, polling for confirmed)")

    async def _fetch_forecasts(self, resolution: int) -> dict[str, ChannelData] | None:
        """Fetch forecasts. Returns data with forecasts or None on failure."""
        try:
            response = await self.hass.async_add_executor_job(
                lambda: self._api.get_current_prices_with_http_info(
                    self.site_id,
                    next=FORECAST_INTERVALS,
                    previous=0,
                    resolution=resolution,
                )
            )
            # Parse rate limit headers from successful response
            self._parse_rate_limit_headers(response.headers)
            self._set_api_status(HTTPStatus.OK)

            if response.data is None:
                _LOGGER.debug("API returned no forecast data")
                return None
            data = self._interval_processor.process_intervals(response.data)
            _LOGGER.debug("Fetched %d forecast intervals", FORECAST_INTERVALS)
            return data
        except ApiException as err:
            if err.status is not None:
                self._set_api_status(err.status)
                if err.status == HTTP_TOO_MANY_REQUESTS:
                    reset_seconds = self._get_reset_from_error(err)
                    self._rate_limiter.record_rate_limit(reset_seconds)
                else:
                    _LOGGER.warning("Failed to fetch forecasts: API error %d", err.status)
            else:
                _LOGGER.warning("Failed to fetch forecasts: %s", err.reason)
            return None
        except Exception as err:
            _LOGGER.warning("Failed to fetch forecasts: %s", err)
            return None

    def _update_from_sources(self) -> None:
        """Update current_data from the merged data sources."""
        result = self._data_sources.get_merged_data()
        self.current_data = result.data
        self.data_source = result.source

    def _log_price_data(self, data: dict[str, ChannelData], source: str) -> None:
        """Log price data in a consistent format regardless of source."""
        general_data = data.get(CHANNEL_GENERAL, {})
        feed_in_data = data.get(CHANNEL_FEED_IN, {})

        if general_data or feed_in_data:
            general_price = general_data.get(ATTR_PER_KWH)
            feed_in_price = feed_in_data.get(ATTR_PER_KWH)
            general_estimate = general_data.get(ATTR_ESTIMATE, "N/A")
            feed_in_estimate = feed_in_data.get(ATTR_ESTIMATE, "N/A")

            _LOGGER.debug(
                "%s update: general=%.4f (estimate=%s), feedIn=%.4f (estimate=%s)",
                source,
                general_price if general_price is not None else 0,
                general_estimate,
                feed_in_price if feed_in_price is not None else 0,
                feed_in_estimate,
            )

    @callback
    def update_from_websocket(self, data: dict[str, ChannelData]) -> None:
        """Update data from websocket."""
        self._log_price_data(data, "WebSocket")

        self._data_sources.update_websocket(data)

        # Merge and notify listeners
        self._update_from_sources()
        self.async_set_updated_data(self.current_data)

    def get_channel_data(self, channel: str) -> ChannelData | None:
        """Get data for a specific channel."""
        match channel:
            case "general":
                return self.current_data.get("general")
            case "feed_in":
                return self.current_data.get("feed_in")
            case "controlled_load":
                return self.current_data.get("controlled_load")
            case _:
                return None

    def get_price(self, channel: str) -> float | None:
        """Get the current price for a channel."""
        channel_data = self.get_channel_data(channel)
        if channel_data:
            return channel_data.get(ATTR_PER_KWH)
        return None

    def get_forecasts(self, channel: str) -> list[ChannelData]:
        """Get forecasts for a channel."""
        channel_data = self.get_channel_data(channel)
        if channel_data:
            return channel_data.get(ATTR_FORECASTS, [])
        return []

    def get_renewables(self) -> float | None:
        """Get the current renewables percentage."""
        # Renewables is typically on the general channel
        general_data = self.get_channel_data(CHANNEL_GENERAL)
        if general_data:
            return general_data.get(ATTR_RENEWABLES)
        return None

    def is_price_spike(self) -> bool:
        """Check if there's currently a price spike."""
        general_data = self.get_channel_data(CHANNEL_GENERAL)
        if general_data:
            spike_status = general_data.get(ATTR_SPIKE_STATUS)
            if spike_status:
                return spike_status.lower() in ("spike", "potential")
        return False

    def is_demand_window(self) -> bool | None:
        """Check if demand window is currently active."""
        general_data = self.get_channel_data(CHANNEL_GENERAL)
        if general_data:
            return general_data.get(ATTR_DEMAND_WINDOW)
        return None

    def get_tariff_info(self) -> TariffInfoData:
        """Get current tariff information."""
        general_data = self.get_channel_data(CHANNEL_GENERAL)
        if not general_data:
            return {}

        return {
            "period": general_data.get(ATTR_TARIFF_PERIOD),
            "season": general_data.get(ATTR_TARIFF_SEASON),
            "block": general_data.get(ATTR_TARIFF_BLOCK),
            "demand_window": general_data.get(ATTR_DEMAND_WINDOW),
        }

    def get_active_channels(self) -> list[str]:
        """Get list of active channels from the current data."""
        return [
            channel
            for channel in [CHANNEL_GENERAL, CHANNEL_FEED_IN, CHANNEL_CONTROLLED_LOAD]
            if channel in self.current_data
        ]

    def get_site_info(self) -> SiteInfoData:
        """Get site information including channels and tariff codes."""
        return self._site_info

    def get_polling_offset_stats(self) -> PollingOffsetStats:
        """Get polling offset statistics for diagnostics."""
        return self._polling_manager.get_offset_stats()

    def _set_api_status(self, status: int) -> None:
        """Set the last API status code."""
        self._last_api_status = status

    def get_api_status(self) -> int:
        """Get last API status code (200 = OK)."""
        return self._last_api_status

    def _parse_rate_limit_headers(self, headers: dict[str, str] | None) -> None:
        """Parse IETF RateLimit headers from API response.

        See: https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/
        """
        if not headers:
            return

        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Parse ratelimit-policy (e.g., "50;w=300")
        policy = headers_lower.get("ratelimit-policy")
        limit: int | None = None
        window: int | None = None

        if policy:
            # Parse "50;w=300" format
            parts = policy.split(";")
            if parts:
                with contextlib.suppress(ValueError):
                    limit = int(parts[0].strip())
                for part in parts[1:]:
                    if part.strip().startswith("w="):
                        with contextlib.suppress(ValueError):
                            window = int(part.strip()[2:])

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

    def get_rate_limit_info(self) -> RateLimitInfo:
        """Get rate limit information from last API response."""
        return self._rate_limit_info

    def _get_reset_from_error(self, err: ApiException) -> int | None:
        """Extract reset_seconds from ApiException headers."""
        headers = getattr(err, "headers", None)
        if not headers:
            return None

        # HTTPHeaderDict and dict-like objects have .get()
        reset_str = None
        if hasattr(headers, "get"):
            reset_str = headers.get("ratelimit-reset") or headers.get("RateLimit-Reset")

        if reset_str:
            with contextlib.suppress(ValueError):
                return int(reset_str)
        return None
