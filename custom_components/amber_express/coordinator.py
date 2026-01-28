"""Data coordinator for Amber Express integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

from .api_client import AmberApiClient
from .cdf_polling import CDFPollingStats, IntervalObservation
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
from .rate_limiter import ExponentialBackoffRateLimiter
from .smart_polling import SmartPollingManager
from .types import ChannelData, ChannelInfo, CoordinatorData, RateLimitInfo, SiteInfoData, TariffInfoData

_LOGGER = logging.getLogger(__name__)

# Interval detection - check every second to detect 5-minute interval boundaries
_INTERVAL_CHECK_SECONDS = list(range(0, 60, 1))


class AmberDataCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinator for Amber Express data.

    Each coordinator is responsible for a single site (subentry).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        *,
        observations: list[IntervalObservation] | None = None,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            entry: Main config entry (contains API token).
            subentry: Site subentry (contains site-specific config).
            observations: Optional pre-loaded observations.

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

        # Exponential backoff for 429 errors
        self._rate_limiter = ExponentialBackoffRateLimiter()

        # API client (uses rate limiter for backoff)
        self._api_client = AmberApiClient(hass, self.api_token, self._rate_limiter)

        # Interval processor for transforming API responses
        pricing_mode = self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)
        self._interval_processor = IntervalProcessor(pricing_mode)

        # Smart polling manager with CDF strategy
        self._polling_manager = SmartPollingManager(observations)

        # Data source merger for combining polling and websocket data
        self._data_sources = DataSourceMerger()

        # Site info (from subentry or fetched at startup)
        self._site_info: SiteInfoData = self._build_site_info_from_subentry()
        self._site_info_fetched = False

        # Merged data (exposed via data_sources)
        self.current_data: CoordinatorData = {}
        self.data_source: str = DATA_SOURCE_POLLING

        # Poll scheduling state (managed by start/stop)
        self._unsub_time_change: Callable[[], None] | None = None
        self._cancel_next_poll: Callable[[], None] | None = None

    def _get_subentry_option(self, key: str, default: Any) -> Any:
        """Get an option from subentry data."""
        return self.subentry.data.get(key, default)

    def update_pricing_mode(self, new_mode: str) -> None:
        """Update the pricing mode and recreate the interval processor."""
        self._interval_processor = IntervalProcessor(new_mode)

    async def start(self) -> None:
        """Start the coordinator polling lifecycle.

        Performs initial data fetch and sets up interval-aligned polling.
        """
        # Initial fetch
        await self.async_config_entry_first_refresh()

        # Set up interval detection (checks every second for 5-minute boundaries)
        self._unsub_time_change = async_track_time_change(
            self.hass,
            self._on_interval_check,
            second=_INTERVAL_CHECK_SECONDS,
        )

        # Start sub-second polling chain if we don't have confirmed price yet
        self._schedule_next_poll()

        _LOGGER.debug("Coordinator started for site %s", self.subentry.title)

    async def stop(self) -> None:
        """Stop the coordinator polling lifecycle."""
        # Cancel any pending scheduled poll
        if self._cancel_next_poll:
            self._cancel_next_poll()
            self._cancel_next_poll = None

        # Unsubscribe from time change listener
        if self._unsub_time_change:
            self._unsub_time_change()
            self._unsub_time_change = None

        _LOGGER.debug("Coordinator stopped for site %s", self.subentry.title)

    def _cancel_pending_poll(self) -> None:
        """Cancel any pending scheduled poll."""
        if self._cancel_next_poll:
            self._cancel_next_poll()
            self._cancel_next_poll = None

    async def _do_scheduled_poll(self) -> None:
        """Execute the scheduled poll."""
        _LOGGER.debug("Sub-second scheduled poll firing")
        self._cancel_next_poll = None

        # Double-check we still need to poll
        if self._polling_manager.has_confirmed_price:
            _LOGGER.debug("Skipping scheduled poll: already have confirmed price")
            return

        await self.async_refresh()

        # Schedule the next poll if we still don't have confirmed price
        self._schedule_next_poll()

    @callback
    def _on_scheduled_poll(self, _now: datetime) -> None:
        """Handle the async_call_later callback by creating a task."""
        self.hass.async_create_task(self._do_scheduled_poll())

    def _schedule_next_poll(self) -> None:
        """Schedule the next poll using sub-second precision."""
        self._cancel_pending_poll()

        # Don't schedule if we have confirmed price
        if self._polling_manager.has_confirmed_price:
            _LOGGER.debug("Not scheduling poll: already have confirmed price")
            return

        # If rate limited, schedule a resume when rate limit expires
        if self._rate_limiter.is_limited():
            remaining = self._rate_limiter.remaining_seconds()
            if remaining > 0:
                _LOGGER.debug("Rate limit active, scheduling resume in %.0fs", remaining + 1)
                # Schedule resume 1 second after rate limit expires
                self._cancel_next_poll = async_call_later(
                    self.hass,
                    remaining + 1,
                    self._on_scheduled_poll,
                )
            return

        delay = self._polling_manager.get_next_poll_delay()
        if delay is None:
            _LOGGER.debug("Not scheduling poll: no delay returned (no more polls)")
            return

        _LOGGER.debug("Scheduling next poll in %.2fs", delay)

        # Schedule the next poll with sub-second precision
        self._cancel_next_poll = async_call_later(
            self.hass,
            delay,
            self._on_scheduled_poll,
        )

    async def _on_interval_check(self, _now: object) -> None:
        """Check for new interval and start sub-second polling chain."""
        # Check if this is a new interval
        if not self._polling_manager.check_new_interval(
            has_data=bool(self.current_data),
            rate_limit_info=self._api_client.rate_limit_info,
        ):
            return

        # New interval - cancel any pending poll from previous interval
        self._cancel_pending_poll()

        # New interval - do immediate first poll
        await self.async_refresh()

        # Start the sub-second polling chain for confirmatory polls
        self._schedule_next_poll()

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

    @property
    def has_confirmed_price(self) -> bool:
        """Check if we have a confirmed price for this interval."""
        return self._polling_manager.has_confirmed_price

    @property
    def is_rate_limited(self) -> bool:
        """Check if we're currently in rate limit backoff."""
        return self._rate_limiter.is_limited()

    def rate_limit_remaining_seconds(self) -> float:
        """Get remaining seconds until rate limit expires."""
        return self._rate_limiter.remaining_seconds()

    async def _async_update_data(self) -> CoordinatorData:
        """Fetch data from Amber API using smart polling."""
        # Fetch site info on first run (for tariff codes etc.)
        if not self._site_info_fetched:
            try:
                await self._fetch_site_info()
            except Exception as err:
                _LOGGER.warning("Failed to fetch site info: %s", err)
            self._site_info_fetched = True

        await self._fetch_amber_data()

        # Merge data from polling and websocket
        self._update_from_sources()

        return self.current_data

    async def _fetch_site_info(self) -> None:
        """Fetch site information including channels and tariff codes."""
        _LOGGER.debug("Fetching site info for site %s", self.site_id)

        sites = await self._api_client.fetch_sites()
        if sites is None:
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

        result = await self._api_client.fetch_current_prices(
            self.site_id,
            next_intervals=next_intervals,
            resolution=resolution,
        )

        # Update polling manager with rate limit info
        self._polling_manager.update_budget(self._api_client.rate_limit_info)

        if result.intervals is None:
            if not result.rate_limited:
                _LOGGER.debug("API returned no data")
            return

        # Process the intervals
        data = self._interval_processor.process_intervals(result.intervals)
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
            # Record observation for CDF strategy
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
        result = await self._api_client.fetch_current_prices(
            self.site_id,
            next_intervals=FORECAST_INTERVALS,
            resolution=resolution,
        )

        if result.intervals is None:
            if not result.rate_limited:
                _LOGGER.debug("API returned no forecast data")
            return None

        data = self._interval_processor.process_intervals(result.intervals)
        _LOGGER.debug("Fetched %d forecast intervals", FORECAST_INTERVALS)
        return data

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

    def get_cdf_polling_stats(self) -> CDFPollingStats:
        """Get CDF polling statistics for diagnostics."""
        return self._polling_manager.get_cdf_stats()

    def get_api_status(self) -> int:
        """Get last API status code (200 = OK)."""
        return self._api_client.last_status

    def get_rate_limit_info(self) -> RateLimitInfo:
        """Get rate limit information from last API response."""
        return self._api_client.rate_limit_info
