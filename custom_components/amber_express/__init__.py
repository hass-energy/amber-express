"""Amber Express integration for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change

from .cdf_storage import CDFObservationStore
from .const import (
    CONF_API_TOKEN,
    CONF_ENABLE_WEBSOCKET,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    DEFAULT_ENABLE_WEBSOCKET,
    PRICING_MODE_AEMO,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from .coordinator import AmberDataCoordinator
from .websocket import AmberWebSocketClient

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

# Interval detection - check every second to detect 5-minute interval boundaries
# Sub-second poll timing is handled by async_call_later chains
INTERVAL_CHECK_SECONDS = list(range(0, 60, 1))

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT]


@dataclass(slots=True)
class SiteRuntimeData:
    """Runtime data for a single site (subentry)."""

    coordinator: AmberDataCoordinator
    websocket_client: AmberWebSocketClient | None = None
    unsub_time_change: Callable[[], None] | None = None
    cancel_next_poll: Callable[[], None] | None = None


@dataclass(slots=True)
class AmberRuntimeData:
    """Runtime data for Amber Express integration."""

    sites: dict[str, SiteRuntimeData] = field(default_factory=dict)


type AmberConfigEntry = ConfigEntry[AmberRuntimeData | None]


async def async_setup_entry(hass: HomeAssistant, entry: AmberConfigEntry) -> bool:
    """Set up Amber Express from a config entry."""
    runtime_data = AmberRuntimeData()
    entry.runtime_data = runtime_data

    # Migrate legacy pricing mode values
    legacy_pricing_modes = {"aemo": PRICING_MODE_AEMO, "app": PRICING_MODE_APP}
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue
        current_mode = subentry.data.get(CONF_PRICING_MODE)
        if current_mode in legacy_pricing_modes:
            updated_data = dict(subentry.data)
            updated_data[CONF_PRICING_MODE] = legacy_pricing_modes[current_mode]
            hass.config_entries.async_update_subentry(entry, subentry, data=updated_data)

    # Set up each site subentry
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        await _setup_site(hass, entry, subentry, runtime_data)

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for subentry changes
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def _setup_site(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
    runtime_data: AmberRuntimeData,
) -> None:
    """Set up a single site from a subentry."""
    subentry_id = subentry.subentry_id

    # Create and load CDF observation store
    cdf_store = CDFObservationStore(hass, subentry_id)
    observations = await cdf_store.async_load()

    # Create the data coordinator for this site
    coordinator = AmberDataCoordinator(hass, entry, subentry, cdf_store=cdf_store, observations=observations)

    # Create WebSocket client if enabled
    websocket_enabled = subentry.data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET)
    websocket_client: AmberWebSocketClient | None = None

    if websocket_enabled:
        websocket_client = AmberWebSocketClient(
            hass=hass,
            api_token=entry.data[CONF_API_TOKEN],
            site_id=subentry.data[CONF_SITE_ID],
            on_message=coordinator.update_from_websocket,
        )

    # Store site runtime data (before setting up polling so callbacks can access it)
    site_data = SiteRuntimeData(
        coordinator=coordinator,
        websocket_client=websocket_client,
    )
    runtime_data.sites[subentry_id] = site_data

    def _cancel_pending_poll() -> None:
        """Cancel any pending scheduled poll."""
        if site_data.cancel_next_poll:
            site_data.cancel_next_poll()
            site_data.cancel_next_poll = None

    async def _do_scheduled_poll() -> None:
        """Execute the scheduled poll."""
        _LOGGER.debug("Sub-second scheduled poll firing")
        site_data.cancel_next_poll = None

        # Double-check we still need to poll
        if coordinator.has_confirmed_price:
            _LOGGER.debug("Skipping scheduled poll: already have confirmed price")
            return

        await coordinator.async_refresh()

        # Schedule the next poll if we still don't have confirmed price
        _schedule_next_poll()

    @callback
    def _on_scheduled_poll(_now: datetime) -> None:
        """Handle the async_call_later callback by creating a task."""
        hass.async_create_task(_do_scheduled_poll())

    def _schedule_next_poll() -> None:
        """Schedule the next poll using sub-second precision."""
        _cancel_pending_poll()

        # Don't schedule if we have confirmed price
        if coordinator.has_confirmed_price:
            _LOGGER.debug("Not scheduling poll: already have confirmed price")
            return

        # If rate limited, schedule a resume when rate limit expires
        if coordinator.is_rate_limited:
            remaining = coordinator.rate_limit_remaining_seconds()
            if remaining > 0:
                _LOGGER.debug("Rate limit active, scheduling resume in %.0fs", remaining + 1)
                # Schedule resume 1 second after rate limit expires
                site_data.cancel_next_poll = async_call_later(
                    hass,
                    remaining + 1,
                    _on_scheduled_poll,
                )
            return

        delay = coordinator.get_next_poll_delay()
        if delay is None:
            _LOGGER.debug("Not scheduling poll: no delay returned (no more polls)")
            return

        _LOGGER.debug("Scheduling next poll in %.2fs", delay)

        # Schedule the next poll with sub-second precision
        site_data.cancel_next_poll = async_call_later(
            hass,
            delay,
            _on_scheduled_poll,
        )

    async def _check_interval(_now: object) -> None:
        """Check for new interval and start sub-second polling chain."""
        # Check if this is a new interval
        if not coordinator.check_new_interval():
            return

        # New interval - cancel any pending poll from previous interval
        _cancel_pending_poll()

        # New interval - do immediate first poll
        await coordinator.async_refresh()

        # Start the sub-second polling chain for confirmatory polls
        _schedule_next_poll()

    unsub_time_change = async_track_time_change(
        hass,
        _check_interval,
        second=INTERVAL_CHECK_SECONDS,
    )
    site_data.unsub_time_change = unsub_time_change

    # Initial fetch
    await coordinator.async_config_entry_first_refresh()

    # Start sub-second polling chain if we don't have confirmed price yet
    _schedule_next_poll()

    # Start WebSocket client if enabled
    if websocket_client:
        await websocket_client.start()

    _LOGGER.debug("Site %s set up successfully", subentry.title)


async def _teardown_site(
    hass: HomeAssistant,  # noqa: ARG001
    site_data: SiteRuntimeData,
) -> None:
    """Tear down a single site."""
    # Cancel any pending scheduled poll
    if site_data.cancel_next_poll:
        site_data.cancel_next_poll()

    # Unsubscribe from time change listener
    if site_data.unsub_time_change:
        site_data.unsub_time_change()

    # Stop WebSocket client
    if site_data.websocket_client:
        await site_data.websocket_client.stop()


async def async_unload_entry(hass: HomeAssistant, entry: AmberConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and entry.runtime_data:
        # Tear down all sites
        for site_data in entry.runtime_data.sites.values():
            await _teardown_site(hass, site_data)
        entry.runtime_data = None

    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: AmberConfigEntry) -> None:
    """Handle options update or subentry changes."""
    _LOGGER.info("Amber Express configuration changed, reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
