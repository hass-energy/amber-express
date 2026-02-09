"""Data coordinator for Amber Express integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from amberelectric.models import Site, TariffInformation
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

from .api_client import AmberApiClient, AmberApiError, RateLimitedError
from .cdf_polling import CDFPollingStats, IntervalObservation
from .cdf_storage import CDFObservationStore
from .const import (
    ATTR_DEMAND_WINDOW,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_NEM_TIME,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_START_TIME,
    ATTR_TARIFF_BLOCK,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_API_TOKEN,
    CONF_CONFIRMATION_TIMEOUT,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_WAIT_FOR_CONFIRMED,
    DATA_SOURCE_POLLING,
    DEFAULT_CONFIRMATION_TIMEOUT,
    DEFAULT_PRICING_MODE,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
    FORECAST_INTERVALS,
)
from .data_source import DataSourceMerger
from .interval_processor import IntervalProcessor
from .rate_limiter import ExponentialBackoffRateLimiter
from .smart_polling import SmartPollingManager
from .types import ChannelData, CoordinatorData, RateLimitInfo

_LOGGER = logging.getLogger(__name__)

# Interval detection - check every second to detect interval boundaries
_INTERVAL_CHECK_SECONDS = list(range(0, 60, 1))

# Minimum forecast entries needed to push held price (current + next interval)
_MIN_FORECASTS_FOR_HELD = 2

# Time attributes to take from the next forecast so the held entry is time-aligned
_INTERVAL_TIME_ATTRS = (ATTR_START_TIME, ATTR_END_TIME, ATTR_NEM_TIME)

# Push held price this many seconds before the boundary so HAEO sees aligned data
_PRE_BOUNDARY_LEAD_SECONDS = 1


class AmberDataCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Orchestrates data fetching and polling lifecycle for a single Amber site.

    Responsibilities:
    - Polling lifecycle management (start/stop, interval detection, scheduling)
    - Deciding WHEN to fetch (first poll vs subsequent, confirmed vs estimate logic)
    - Processing fetched data through IntervalProcessor
    - Merging data from polling and websocket sources via DataSourceMerger
    - Providing data accessor methods for sensors (get_price, get_forecasts, etc.)
    - Handling WebSocket update callbacks

    Each coordinator instance manages a single site (subentry).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        *,
        cdf_store: CDFObservationStore,
        observations: list[IntervalObservation],
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            entry: Main config entry (contains API token).
            subentry: Site subentry (contains site-specific config).
            cdf_store: Store for persisting CDF observations.
            observations: Pre-loaded observations (from storage or cold start).

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

        # Store for persisting CDF observations
        self._cdf_store = cdf_store

        # Store observations for polling manager creation in start()
        self._observations: list[IntervalObservation] = observations

        # Polling manager is created in start() after site info is fetched
        self._polling_manager: SmartPollingManager

        # Data source merger for combining polling and websocket data
        self._data_sources = DataSourceMerger()

        # Site info is fetched in start() - required for operation
        self._site: Site

        # Merged data (exposed via data_sources)
        self.current_data: CoordinatorData = {}
        self.data_source: str = DATA_SOURCE_POLLING

        # Poll scheduling state (managed by start/stop)
        self._unsub_time_change: Callable[[], None] | None = None
        self._cancel_next_poll: Callable[[], None] | None = None

        # Confirmation timeout state
        self._cancel_confirmation_timeout: Callable[[], None] | None = None
        self._confirmation_timeout_expired: bool = False

        # Pre-boundary held price: True once we've pushed for the upcoming boundary
        self._held_price_pushed: bool = False

    def _get_subentry_option(self, key: str, default: Any) -> Any:
        """Get an option from subentry data."""
        return self.subentry.data.get(key, default)

    def update_pricing_mode(self, new_mode: str) -> None:
        """Update the pricing mode and recreate the interval processor."""
        self._interval_processor = IntervalProcessor(new_mode)

    async def start(self) -> None:
        """Start the coordinator polling lifecycle.

        Fetches site info, creates the polling manager, then starts polling.
        Raises ConfigEntryNotReady if site info cannot be fetched.
        """
        # Fetch site info first to get interval_length and rate limit info
        self._site = await self._fetch_site_info()

        # Create polling manager with site's interval length
        self._polling_manager = SmartPollingManager(
            int(self._site.interval_length),
            self._observations,
        )

        # Initial fetch
        await self.async_config_entry_first_refresh()

        # Set up interval detection (checks every second for interval boundaries)
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

        # Cancel any pending confirmation timeout
        self._cancel_pending_confirmation_timeout()

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

    def _cancel_pending_confirmation_timeout(self) -> None:
        """Cancel any pending confirmation timeout."""
        if self._cancel_confirmation_timeout:
            self._cancel_confirmation_timeout()
            self._cancel_confirmation_timeout = None

    def _schedule_confirmation_timeout(self) -> None:
        """Schedule the confirmation timeout callback for this interval."""
        self._cancel_pending_confirmation_timeout()
        self._confirmation_timeout_expired = False

        wait_for_confirmed = self._get_subentry_option(CONF_WAIT_FOR_CONFIRMED, DEFAULT_WAIT_FOR_CONFIRMED)
        timeout = self._get_subentry_option(CONF_CONFIRMATION_TIMEOUT, DEFAULT_CONFIRMATION_TIMEOUT)

        if not wait_for_confirmed or timeout <= 0:
            return

        _LOGGER.debug("Scheduling confirmation timeout in %ds", timeout)
        self._cancel_confirmation_timeout = async_call_later(self.hass, timeout, self._on_confirmation_timeout)

    @callback
    def _on_confirmation_timeout(self, _now: datetime) -> None:
        """Handle confirmation timeout expiry."""
        self._cancel_confirmation_timeout = None
        self._confirmation_timeout_expired = True
        _LOGGER.debug("Confirmation timeout expired, updating sensors with estimate")
        self._update_from_sources()
        self.async_set_updated_data(self.current_data)

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

    def _seconds_until_next_boundary(self) -> float:
        """Seconds until the next interval boundary (same logic as SmartPollingManager)."""
        now = datetime.now(UTC)
        length = int(self._site.interval_length)
        current_minute = (now.minute // length) * length
        current_start = now.replace(minute=current_minute, second=0, microsecond=0)
        next_boundary = current_start + timedelta(minutes=length)
        return (next_boundary - now).total_seconds()

    def _push_held_price_at_boundary(self) -> bool:
        """Push a sensor update at interval boundary using previous confirmed price.

        Shifts the forecast list forward and holds the previous interval's price
        for the new current interval so HAEO sees time-aligned data with zero
        API latency. Only runs when wait_for_confirmed is True.

        Returns:
            True if the held price was applied and listeners were notified, False otherwise.

        """
        wait_for_confirmed = self._get_subentry_option(CONF_WAIT_FOR_CONFIRMED, DEFAULT_WAIT_FOR_CONFIRMED)
        confirmation_timeout = self._get_subentry_option(CONF_CONFIRMATION_TIMEOUT, DEFAULT_CONFIRMATION_TIMEOUT)
        if not wait_for_confirmed or confirmation_timeout <= 0:
            return False
        if not self.current_data:
            return False

        applied_held = False
        for channel, channel_data in self.current_data.items():
            if channel.startswith("_"):
                continue
            if not channel_data or not isinstance(channel_data, dict):
                continue
            forecasts = channel_data.get(ATTR_FORECASTS)
            if not forecasts or len(forecasts) < _MIN_FORECASTS_FOR_HELD:
                continue

            next_entry = forecasts[1]
            for attr in _INTERVAL_TIME_ATTRS:
                val = next_entry.get(attr)
                if val is not None:
                    channel_data[attr] = val
            # Forward-project demand window from the next interval so the
            # sensor applies (or stops applying) the demand window surcharge
            if ATTR_DEMAND_WINDOW in next_entry:
                channel_data[ATTR_DEMAND_WINDOW] = next_entry[ATTR_DEMAND_WINDOW]
            elif ATTR_DEMAND_WINDOW in channel_data:
                del channel_data[ATTR_DEMAND_WINDOW]
            channel_data[ATTR_ESTIMATE] = True
            current_snapshot = {k: v for k, v in channel_data.items() if k != ATTR_FORECASTS}
            channel_data[ATTR_FORECASTS] = [current_snapshot, *forecasts[2:]]
            applied_held = True

        if not applied_held:
            return False

        self.async_set_updated_data(self.current_data)
        _LOGGER.debug("Pushed held price at interval boundary")
        return True

    async def _on_interval_check(self, _now: object) -> None:
        """Check for new interval and start sub-second polling chain."""
        # Pre-boundary: push held price before the boundary crosses so HAEO sees aligned data
        if (
            not self._held_price_pushed
            and self._seconds_until_next_boundary() <= _PRE_BOUNDARY_LEAD_SECONDS
            and self._push_held_price_at_boundary()
        ):
            self._held_price_pushed = True

        # Detect actual boundary
        if not self._polling_manager.check_new_interval(has_data=bool(self.current_data)):
            return

        self._held_price_pushed = False

        # New interval - cancel any pending poll from previous interval
        self._cancel_pending_poll()

        # New interval - schedule confirmation timeout
        self._schedule_confirmation_timeout()

        # New interval - do immediate first poll
        await self.async_refresh()

        # Start the sub-second polling chain for confirmatory polls
        self._schedule_next_poll()

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
        await self._fetch_amber_data()
        return self.current_data

    async def _fetch_site_info(self) -> Site:
        """Fetch site information from the API.

        Returns the Site object for the configured site ID.
        Raises ConfigEntryNotReady if site info cannot be fetched.
        """
        _LOGGER.debug("Fetching site info for site %s", self.site_id)

        try:
            sites = await self._api_client.fetch_sites()
        except RateLimitedError as err:
            msg = "Rate limited while fetching site info"
            raise ConfigEntryNotReady(msg) from err
        except AmberApiError as err:
            msg = f"Failed to fetch site info: {err}"
            raise ConfigEntryNotReady(msg) from err

        # Find our site
        for site in sites:
            if site.id == self.site_id:
                _LOGGER.debug(
                    "Fetched site info: id=%s, network=%s, interval_length=%s",
                    site.id,
                    site.network,
                    site.interval_length,
                )
                return site

        msg = f"Site {self.site_id} not found in API response"
        raise ConfigEntryNotReady(msg)

    async def _fetch_amber_data(self) -> None:
        """Fetch current prices and forecasts from Amber API."""
        resolution = int(self._site.interval_length)

        # Skip if we already have confirmed price for this interval
        if self._polling_manager.has_confirmed_price:
            return

        # Record poll started
        self._polling_manager.on_poll_started()

        _LOGGER.debug(
            "Polling Amber API (poll #%d for this interval)",
            self._polling_manager.poll_count_this_interval,
        )

        try:
            intervals = await self._api_client.fetch_current_prices(
                self.site_id,
                next_intervals=FORECAST_INTERVALS,
                resolution=resolution,
            )
        except RateLimitedError:
            return
        except AmberApiError as err:
            _LOGGER.debug("API error: %s", err)
            return
        finally:
            # Update polling manager with rate limit info regardless of success/failure
            self._polling_manager.update_budget(self._api_client.rate_limit_info)

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

        # Always store latest data in data sources
        self._data_sources.update_polling(data)

        if is_estimate is False:
            # Confirmed price: cancel timeout, push to sensors and stop polling
            self._cancel_pending_confirmation_timeout()
            self._polling_manager.on_confirmed_received()
            await self._cdf_store.async_save(self._polling_manager.observations)
            self._update_from_sources()
            _LOGGER.info("Confirmed price received, stopping polling for this interval")
        else:
            # Estimated price: only push to sensors if not waiting or timeout expired
            self._polling_manager.on_estimate_received()
            if not wait_for_confirmed or self._confirmation_timeout_expired:
                self._update_from_sources()
                _LOGGER.debug("Estimate received, updating sensors")
            else:
                _LOGGER.debug("Estimate received, waiting for confirmed before updating sensors")

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

    def get_tariff_info(self) -> TariffInformation | None:
        """Get current tariff information."""
        general_data = self.get_channel_data(CHANNEL_GENERAL)
        if not general_data:
            return None

        # Only return tariff info if we have any tariff data
        period = general_data.get(ATTR_TARIFF_PERIOD)
        season = general_data.get(ATTR_TARIFF_SEASON)
        block = general_data.get(ATTR_TARIFF_BLOCK)
        demand_window = general_data.get(ATTR_DEMAND_WINDOW)

        if period is None and season is None and block is None and demand_window is None:
            return None

        return TariffInformation(
            period=period,
            season=season,
            block=block,
            demand_window=demand_window,
        )

    def get_active_channels(self) -> list[str]:
        """Get list of active channels from the current data."""
        return [
            channel
            for channel in [CHANNEL_GENERAL, CHANNEL_FEED_IN, CHANNEL_CONTROLLED_LOAD]
            if channel in self.current_data
        ]

    def get_site_info(self) -> Site:
        """Get site information including channels and tariff codes."""
        return self._site

    def get_cdf_polling_stats(self) -> CDFPollingStats:
        """Get CDF polling statistics for diagnostics."""
        return self._polling_manager.get_cdf_stats()

    def get_next_poll_time(self) -> datetime | None:
        """Get the timestamp of the next scheduled poll."""
        return self._polling_manager.get_next_poll_time()

    def get_api_status(self) -> int:
        """Get last API status code (200 = OK)."""
        return self._api_client.last_status

    def get_rate_limit_info(self) -> RateLimitInfo:
        """Get rate limit information from last API response."""
        return self._api_client.rate_limit_info
