"""Data coordinator for Amber Express integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any

import amberelectric
from amberelectric.api import amber_api
from amberelectric.configuration import Configuration
from amberelectric.models import CurrentInterval, ForecastInterval, Interval
from amberelectric.rest import ApiException
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DESCRIPTOR,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_NEM_TIME,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_SPOT_PER_KWH,
    ATTR_START_TIME,
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
    DATA_SOURCE_WEBSOCKET,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
    FORECAST_INTERVALS,
    PRICING_MODE_APP,
)

_LOGGER = logging.getLogger(__name__)

# HTTP status codes
HTTP_TOO_MANY_REQUESTS = 429

# Map Amber channel types to our constants
CHANNEL_TYPE_MAP = {
    "general": CHANNEL_GENERAL,
    "feedIn": CHANNEL_FEED_IN,
    "controlledLoad": CHANNEL_CONTROLLED_LOAD,
}


class AmberDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Amber Express data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # Polling is handled by async_track_time_change for clock alignment
        )
        self.entry = entry
        self.api_token = entry.data[CONF_API_TOKEN]
        self.site_id = entry.data[CONF_SITE_ID]

        # API client
        configuration = Configuration(access_token=self.api_token)
        self._api = amber_api.AmberApi(amberelectric.ApiClient(configuration))

        # Smart polling state
        self._current_interval_start: datetime | None = None
        self._has_confirmed_price = False
        self._last_poll_time: datetime | None = None
        self._poll_count_this_interval = 0

        # Rate limiting: 50 requests per 5 minutes, we'll limit to 8 per interval (48/30min)
        self._max_polls_per_interval = 8

        # Exponential backoff for 429 errors
        self._rate_limit_backoff_seconds = 0
        self._rate_limit_until: datetime | None = None

        # Pending forecasts fetch (retry if 429)
        self._forecasts_pending = False

        # Data from different sources
        self._polling_data: dict[str, Any] = {}
        self._websocket_data: dict[str, Any] = {}
        self._polling_timestamp: datetime | None = None
        self._websocket_timestamp: datetime | None = None

        # Site info (fetched at startup)
        self._site_info: dict[str, Any] = {}
        self._site_info_fetched = False

        # Merged data
        self.current_data: dict[str, Any] = {}
        self.data_source: str = DATA_SOURCE_POLLING

    def _get_current_5min_interval(self) -> datetime:
        """Get the start of the current 5-minute interval."""
        now = datetime.now(UTC)
        # Round down to nearest 5 minutes
        minutes = (now.minute // 5) * 5
        return now.replace(minute=minutes, second=0, microsecond=0)

    def _should_poll_now(self) -> bool:
        """Determine if we should poll. Simple logic: poll every 5 seconds until confirmed."""
        current_interval = self._get_current_5min_interval()

        # Always poll on first run (no data yet)
        if not self.current_data:
            _LOGGER.debug("First poll - fetching initial data")
            return True

        # Reset state if we've moved to a new interval
        if self._current_interval_start != current_interval:
            self._current_interval_start = current_interval
            self._has_confirmed_price = False
            self._forecasts_pending = False
            self._poll_count_this_interval = 0
            _LOGGER.debug("New 5-minute interval started: %s", current_interval)
            return True  # Always poll at start of new interval

        # Don't poll if we already have confirmed price (unless forecasts pending)
        if self._has_confirmed_price and not self._forecasts_pending:
            return False

        # If forecasts pending, check rate limit backoff before retrying
        if self._forecasts_pending and self._rate_limit_until and datetime.now(UTC) < self._rate_limit_until:
            return False

        # Rate limit: max polls per interval (API limit is 50 per 5 min)
        if self._poll_count_this_interval >= self._max_polls_per_interval:
            _LOGGER.debug(
                "Rate limit reached (%d polls), waiting for next interval",
                self._poll_count_this_interval,
            )
            return False

        return True

    def should_poll(self) -> bool:
        """Check if polling is needed (public interface for __init__.py)."""
        return self._should_poll_now()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Amber API using smart polling."""
        # Fetch site info on first run (for tariff codes etc.)
        if not self._site_info_fetched:
            try:
                await self._fetch_site_info()
            except Exception as err:
                _LOGGER.warning("Failed to fetch site info: %s", err)
            self._site_info_fetched = True

        # Check if we should poll
        if not self._should_poll_now():
            # Return existing data without making an API call
            return self.current_data

        try:
            await self._fetch_amber_data()
        except amberelectric.ApiException as err:
            msg = f"Error communicating with Amber API: {err}"
            raise UpdateFailed(msg) from err
        except Exception as err:
            msg = f"Unexpected error: {err}"
            raise UpdateFailed(msg) from err

        # Merge data from polling and websocket
        self._merge_data()

        return self.current_data

    async def _fetch_site_info(self) -> None:
        """Fetch site information including channels and tariff codes."""
        _LOGGER.debug("Fetching site info for site %s", self.site_id)

        try:
            sites = await self.hass.async_add_executor_job(self._api.get_sites)
        except Exception as err:
            _LOGGER.warning("Failed to fetch sites: %s", err)
            return

        # Find our site
        for site in sites:
            if site.id == self.site_id:
                # Extract channel info including tariff codes
                channels_info = []
                for ch in site.channels or []:
                    channel_type = ch.type.value if hasattr(ch.type, "value") else str(ch.type)
                    channels_info.append(
                        {
                            "identifier": getattr(ch, "identifier", None),
                            "type": channel_type,
                            "tariff": getattr(ch, "tariff", None),
                        }
                    )

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
        now = datetime.now(UTC)

        # Check if we're in a rate limit backoff period
        if self._rate_limit_until and now < self._rate_limit_until:
            remaining = (self._rate_limit_until - now).total_seconds()
            _LOGGER.debug("Rate limit backoff: %.0f seconds remaining", remaining)
            return

        # Use site's interval_length for resolution (default to 30 if not available)
        resolution = int(self._site_info.get("interval_length", 30))

        # If we have confirmed price but forecasts are pending, only fetch forecasts
        if self._has_confirmed_price and self._forecasts_pending:
            _LOGGER.debug("Retrying forecast fetch...")
            forecasts_fetched = await self._fetch_forecasts(resolution)
            if forecasts_fetched:
                self._forecasts_pending = False
                self._polling_data = forecasts_fetched
                self._polling_timestamp = now
                self._merge_data()
                self.async_set_updated_data(self.current_data)
                _LOGGER.info("Forecasts fetched successfully on retry")
            return

        self._last_poll_time = now
        self._poll_count_this_interval += 1

        _LOGGER.debug(
            "Polling Amber API (poll #%d for this interval)",
            self._poll_count_this_interval,
        )

        try:
            # First fetch current price only (no forecasts) to check if confirmed
            intervals = await self.hass.async_add_executor_job(
                lambda: self._api.get_current_prices(
                    self.site_id,
                    next=0,
                    previous=0,
                    resolution=resolution,
                )
            )
            # Reset backoff on success
            self._rate_limit_backoff_seconds = 0
            self._rate_limit_until = None
        except ApiException as err:
            if err.status == HTTP_TOO_MANY_REQUESTS:
                # Rate limited - apply exponential backoff
                if self._rate_limit_backoff_seconds == 0:
                    self._rate_limit_backoff_seconds = 10
                else:
                    self._rate_limit_backoff_seconds = min(self._rate_limit_backoff_seconds * 2, 300)
                self._rate_limit_until = now + timedelta(seconds=self._rate_limit_backoff_seconds)
                _LOGGER.warning(
                    "Rate limited (429). Backing off for %d seconds",
                    self._rate_limit_backoff_seconds,
                )
            else:
                _LOGGER.warning("Amber API error (%d): %s", err.status, err.reason)
            return
        except Exception as err:
            _LOGGER.warning("Failed to fetch Amber data: %s", err)
            return

        # Process the intervals
        data = self._process_intervals(intervals)
        general_data = data.get(CHANNEL_GENERAL, {})

        if not general_data:
            _LOGGER.debug("Poll %d: No data returned", self._poll_count_this_interval)
            return

        # Log using centralized format
        self._log_price_data(data, f"Poll #{self._poll_count_this_interval}")

        is_estimate = general_data.get(ATTR_ESTIMATE, True)
        wait_for_confirmed = self.entry.options.get(CONF_WAIT_FOR_CONFIRMED, DEFAULT_WAIT_FOR_CONFIRMED)

        # Confirmed price: fetch full forecasts and update
        if is_estimate is False:
            # Try to fetch forecasts
            forecasts_fetched = await self._fetch_forecasts(resolution)
            if not forecasts_fetched:
                self._forecasts_pending = True
            else:
                self._forecasts_pending = False
                data = forecasts_fetched

            self._polling_data = data
            self._polling_timestamp = now
            self._has_confirmed_price = True
            _LOGGER.info("Confirmed price received, stopping polling for this interval")
        # Estimated price: update only if wait_for_confirmed is False
        elif not wait_for_confirmed:
            self._polling_data = data
            self._polling_timestamp = now
            _LOGGER.debug("Estimated price received, updating sensors")
        else:
            _LOGGER.debug("Estimated price received, waiting for confirmed")

    async def _fetch_forecasts(self, resolution: int) -> dict[str, Any] | None:
        """Fetch forecasts. Returns data with forecasts or None on failure."""
        try:
            intervals_with_forecasts = await self.hass.async_add_executor_job(
                lambda: self._api.get_current_prices(
                    self.site_id,
                    next=FORECAST_INTERVALS,
                    previous=0,
                    resolution=resolution,
                )
            )
            data = self._process_intervals(intervals_with_forecasts)
            _LOGGER.debug("Fetched %d forecast intervals", FORECAST_INTERVALS)
            return data
        except ApiException as err:
            if err.status == HTTP_TOO_MANY_REQUESTS:
                _LOGGER.warning("Rate limited fetching forecasts (429). Will retry next cycle.")
            else:
                _LOGGER.warning("Failed to fetch forecasts: API error %d", err.status)
            return None
        except Exception as err:
            _LOGGER.warning("Failed to fetch forecasts: %s", err)
            return None

    def _process_intervals(self, intervals: list) -> dict[str, Any]:
        """Process interval data from the API."""
        data: dict[str, Any] = {}

        # Separate intervals by type and channel
        current_intervals: dict[str, Any] = {}
        forecast_intervals: dict[str, list] = {}

        for interval in intervals:
            # Unwrap Interval wrapper if needed (API returns Interval objects with actual_instance)
            actual = interval
            if isinstance(interval, Interval):
                actual = interval.actual_instance
            if actual is None:
                continue

            # Get channel type from the actual interval
            if not hasattr(actual, "channel_type"):
                _LOGGER.debug("Interval missing channel_type: %s", type(actual).__name__)
                continue

            channel_type_raw = (
                actual.channel_type.value if hasattr(actual.channel_type, "value") else str(actual.channel_type)
            )
            channel = CHANNEL_TYPE_MAP.get(channel_type_raw, channel_type_raw)

            if channel not in forecast_intervals:
                forecast_intervals[channel] = []

            # Determine interval type
            # CurrentInterval = the current price (check estimate field for confirmed status)
            # ActualInterval = historical confirmed prices (past intervals, not current)
            # ForecastInterval = future prediction
            if isinstance(actual, CurrentInterval):
                # CurrentInterval is the current price - always use it
                current_intervals[channel] = actual
            elif isinstance(actual, ForecastInterval):
                forecast_intervals[channel].append(actual)
            # Note: ActualInterval is historical data and not used for current price

        # Process current intervals
        for channel, interval in current_intervals.items():
            channel_data = self._extract_interval_data(interval)
            channel_data[ATTR_FORECASTS] = self._build_forecasts(forecast_intervals.get(channel, []))
            data[channel] = channel_data

        # If we have forecasts but no current interval for a channel, still include forecasts
        for channel, forecasts in forecast_intervals.items():
            if channel not in data and forecasts:
                data[channel] = {
                    ATTR_FORECASTS: self._build_forecasts(forecasts),
                }

        return data

    def _extract_interval_data(self, interval: CurrentInterval | ForecastInterval) -> dict[str, Any]:
        """Extract data from an interval object."""
        pricing_mode = self.entry.options.get(CONF_PRICING_MODE, "aemo")

        # Get the price based on pricing mode (API returns cents, we convert to dollars)
        if pricing_mode == PRICING_MODE_APP:
            # Use advanced_price.predicted if available
            price_cents = None
            if hasattr(interval, "advanced_price") and interval.advanced_price:
                price_cents = getattr(interval.advanced_price, "predicted", None)
            if price_cents is None:
                price_cents = interval.per_kwh
        else:
            # Use per_kwh (AEMO-based)
            price_cents = interval.per_kwh

        # Convert cents to dollars
        price = price_cents / 100 if price_cents is not None else None
        spot_per_kwh_cents = getattr(interval, "spot_per_kwh", None)
        spot_per_kwh = spot_per_kwh_cents / 100 if spot_per_kwh_cents is not None else None

        # Extract descriptor
        descriptor = None
        if hasattr(interval, "descriptor"):
            descriptor = (
                interval.descriptor.value if hasattr(interval.descriptor, "value") else str(interval.descriptor)
            )

        # Extract spike status
        spike_status = None
        if hasattr(interval, "spike_status"):
            spike_status = (
                interval.spike_status.value if hasattr(interval.spike_status, "value") else str(interval.spike_status)
            )

        # Determine estimate status based on interval type
        # ForecastInterval is always estimated, CurrentInterval has an estimate field
        is_estimate = True if isinstance(interval, ForecastInterval) else getattr(interval, "estimate", True)

        data = {
            ATTR_PER_KWH: price,
            ATTR_SPOT_PER_KWH: spot_per_kwh,
            ATTR_START_TIME: interval.start_time.isoformat() if interval.start_time else None,
            ATTR_END_TIME: interval.end_time.isoformat() if interval.end_time else None,
            ATTR_NEM_TIME: getattr(interval, "nem_time", None),
            ATTR_RENEWABLES: getattr(interval, "renewables", None),
            ATTR_DESCRIPTOR: descriptor,
            ATTR_SPIKE_STATUS: spike_status,
            ATTR_ESTIMATE: is_estimate,
        }

        # Add advanced price data if available (convert cents to dollars)
        if hasattr(interval, "advanced_price") and interval.advanced_price:
            low_cents = getattr(interval.advanced_price, "low", None)
            predicted_cents = getattr(interval.advanced_price, "predicted", None)
            high_cents = getattr(interval.advanced_price, "high", None)
            data[ATTR_ADVANCED_PRICE] = {
                "low": low_cents / 100 if low_cents is not None else None,
                "predicted": predicted_cents / 100 if predicted_cents is not None else None,
                "high": high_cents / 100 if high_cents is not None else None,
            }

        # Add tariff information if available
        if hasattr(interval, "tariff_information") and interval.tariff_information:
            tariff = interval.tariff_information
            data[ATTR_DEMAND_WINDOW] = getattr(tariff, "demand_window", None)
            data[ATTR_TARIFF_PERIOD] = getattr(tariff, "period", None)
            data[ATTR_TARIFF_SEASON] = getattr(tariff, "season", None)
            data[ATTR_TARIFF_BLOCK] = getattr(tariff, "block", None)

        return data

    def _build_forecasts(self, forecast_intervals: list) -> list[dict[str, Any]]:
        """Build HAEO-compatible forecast list."""
        pricing_mode = self.entry.options.get(CONF_PRICING_MODE, "aemo")
        forecasts = []

        # Sort by start time
        sorted_intervals = sorted(
            forecast_intervals,
            key=lambda x: x.start_time if x.start_time else datetime.min.replace(tzinfo=UTC),
        )

        for interval in sorted_intervals:
            # Get the price based on pricing mode (API returns cents, we convert to dollars)
            if pricing_mode == PRICING_MODE_APP:
                price_cents = None
                if hasattr(interval, "advanced_price") and interval.advanced_price:
                    price_cents = getattr(interval.advanced_price, "predicted", None)
                if price_cents is None:
                    price_cents = interval.per_kwh
            else:
                price_cents = interval.per_kwh

            # Convert cents to dollars
            price = price_cents / 100 if price_cents is not None else None

            forecast = {
                ATTR_START_TIME: interval.start_time.isoformat() if interval.start_time else None,
                ATTR_PER_KWH: price,
            }

            # Include both pricing values for flexibility (also converted to dollars)
            if hasattr(interval, "advanced_price") and interval.advanced_price:
                advanced_cents = getattr(interval.advanced_price, "predicted", None)
                forecast[ATTR_ADVANCED_PRICE] = advanced_cents / 100 if advanced_cents is not None else None

            forecasts.append(forecast)

        return forecasts

    def _merge_data(self) -> None:
        """Merge data from polling and websocket sources."""
        # Determine which source is fresher
        polling_fresh = self._polling_timestamp is not None
        websocket_fresh = self._websocket_timestamp is not None

        if (
            websocket_fresh
            and polling_fresh
            and self._websocket_timestamp is not None
            and self._polling_timestamp is not None
        ):
            # Use whichever is more recent
            if self._websocket_timestamp > self._polling_timestamp:
                self.current_data = self._websocket_data.copy()
                self.data_source = DATA_SOURCE_WEBSOCKET
            else:
                self.current_data = self._polling_data.copy()
                self.data_source = DATA_SOURCE_POLLING
        elif websocket_fresh:
            self.current_data = self._websocket_data.copy()
            self.data_source = DATA_SOURCE_WEBSOCKET
        elif polling_fresh:
            self.current_data = self._polling_data.copy()
            self.data_source = DATA_SOURCE_POLLING
        else:
            self.current_data = {}

        # Add metadata
        self.current_data["_source"] = self.data_source
        self.current_data["_polling_timestamp"] = (
            self._polling_timestamp.isoformat() if self._polling_timestamp else None
        )
        self.current_data["_websocket_timestamp"] = (
            self._websocket_timestamp.isoformat() if self._websocket_timestamp else None
        )

    def _log_price_data(self, data: dict[str, Any], source: str) -> None:
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
    def update_from_websocket(self, data: dict[str, Any]) -> None:
        """Update data from websocket."""
        self._log_price_data(data, "WebSocket")

        self._websocket_data = data
        self._websocket_timestamp = datetime.now(UTC)

        # Merge and notify listeners
        self._merge_data()
        self.async_set_updated_data(self.current_data)

    def get_channel_data(self, channel: str) -> dict[str, Any] | None:
        """Get data for a specific channel."""
        return self.current_data.get(channel)

    def get_price(self, channel: str) -> float | None:
        """Get the current price for a channel."""
        channel_data = self.get_channel_data(channel)
        if channel_data:
            return channel_data.get(ATTR_PER_KWH)
        return None

    def get_forecasts(self, channel: str) -> list[dict[str, Any]]:
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

    def get_tariff_info(self) -> dict[str, Any]:
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

    def get_site_info(self) -> dict[str, Any]:
        """Get site information including channels and tariff codes."""
        return self._site_info
