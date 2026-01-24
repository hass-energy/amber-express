"""Amber Express integration for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .const import CONF_API_TOKEN, CONF_ENABLE_WEBSOCKET, CONF_SITE_ID, DEFAULT_ENABLE_WEBSOCKET, SUBENTRY_TYPE_SITE
from .coordinator import AmberDataCoordinator
from .websocket import AmberWebSocketClient

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

# Polling seconds - check every second to support 2-second confirmatory polling
# The coordinator's should_poll() decides when to actually make API calls
POLL_SECONDS = list(range(0, 60, 1))

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


@dataclass(slots=True)
class SiteRuntimeData:
    """Runtime data for a single site (subentry)."""

    coordinator: AmberDataCoordinator
    websocket_client: AmberWebSocketClient | None = None
    unsub_time_change: Callable[[], None] | None = None


@dataclass(slots=True)
class AmberRuntimeData:
    """Runtime data for Amber Express integration."""

    sites: dict[str, SiteRuntimeData] = field(default_factory=dict)


type AmberConfigEntry = ConfigEntry[AmberRuntimeData | None]


async def async_setup_entry(hass: HomeAssistant, entry: AmberConfigEntry) -> bool:
    """Set up Amber Express from a config entry."""
    runtime_data = AmberRuntimeData()
    entry.runtime_data = runtime_data

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

    # Create the data coordinator for this site
    coordinator = AmberDataCoordinator(hass, entry, subentry)

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

    # Set up clock-aligned polling for this coordinator
    async def _clock_aligned_poll(_now: object) -> None:
        """Poll at clock-aligned times with smart offset logic."""
        if not coordinator.should_poll():
            return
        await coordinator.async_refresh()

    unsub_time_change = async_track_time_change(
        hass,
        _clock_aligned_poll,
        second=POLL_SECONDS,
    )

    # Store site runtime data
    site_data = SiteRuntimeData(
        coordinator=coordinator,
        websocket_client=websocket_client,
        unsub_time_change=unsub_time_change,
    )
    runtime_data.sites[subentry_id] = site_data

    # Initial fetch
    await coordinator.async_config_entry_first_refresh()

    # Start WebSocket client if enabled
    if websocket_client:
        await websocket_client.start()

    _LOGGER.debug("Site %s set up successfully", subentry.title)


async def _teardown_site(
    hass: HomeAssistant,  # noqa: ARG001
    site_data: SiteRuntimeData,
) -> None:
    """Tear down a single site."""
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
