"""Amber Express integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .const import CONF_API_TOKEN, CONF_ENABLE_WEBSOCKET, CONF_SITE_ID, DEFAULT_ENABLE_WEBSOCKET, DOMAIN
from .coordinator import AmberDataCoordinator
from .websocket import AmberWebSocketClient

_LOGGER = logging.getLogger(__name__)

# Polling seconds (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55)
POLL_SECONDS = list(range(0, 60, 5))

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amber Express from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create the data coordinator
    coordinator = AmberDataCoordinator(hass, entry)

    # Create WebSocket client if enabled
    websocket_enabled = entry.options.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET)
    websocket_client: AmberWebSocketClient | None = None

    if websocket_enabled:
        websocket_client = AmberWebSocketClient(
            hass=hass,
            api_token=entry.data[CONF_API_TOKEN],
            site_id=entry.data[CONF_SITE_ID],
            on_message=coordinator.update_from_websocket,
        )

    # Set up clock-aligned polling (fires at :00, :05, :10, :15, etc.)
    async def _clock_aligned_poll(_now: object) -> None:
        """Poll at clock-aligned times."""
        # Skip refresh if we don't need to poll (confirmed price, no pending forecasts)
        if not coordinator.should_poll():
            return
        await coordinator.async_refresh()

    unsub_time_change = async_track_time_change(
        hass,
        _clock_aligned_poll,
        second=POLL_SECONDS,
    )

    # Store coordinator, websocket client, and cleanup functions
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "websocket_client": websocket_client,
        "unsub_time_change": unsub_time_change,
    }

    # Initial fetch (first refresh)
    await coordinator.async_config_entry_first_refresh()

    # Start WebSocket client if enabled
    if websocket_client:
        await websocket_client.start()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register options update listener
    entry.async_on_unload(entry.add_update_listener(async_options_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)

        # Unsubscribe from time change listener
        unsub_time_change = data.get("unsub_time_change")
        if unsub_time_change:
            unsub_time_change()

        # Stop WebSocket client
        websocket_client = data.get("websocket_client")
        if websocket_client:
            await websocket_client.stop()

    return unload_ok


async def async_options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    # Reload the integration to apply new options
    await hass.config_entries.async_reload(entry.entry_id)
