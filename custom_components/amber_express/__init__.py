"""Amber Express integration for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .cdf_storage import CDFObservationStore
from .const import (
    CONF_API_TOKEN,
    CONF_ENABLE_WEBSOCKET,
    CONF_FORECAST_INTERVALS,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_FORECAST_INTERVALS,
    PRICING_MODE_AEMO,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from .coordinator import AmberDataCoordinator
from .websocket import AmberWebSocketClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT]


@dataclass(slots=True)
class SiteRuntimeData:
    """Runtime data for a single site (subentry)."""

    coordinator: AmberDataCoordinator
    websocket_client: AmberWebSocketClient | None = None


@dataclass(slots=True)
class AmberRuntimeData:
    """Runtime data for Amber Express integration."""

    sites: dict[str, SiteRuntimeData] = field(default_factory=dict)


type AmberConfigEntry = ConfigEntry[AmberRuntimeData | None]


async def async_setup_entry(hass: HomeAssistant, entry: AmberConfigEntry) -> bool:
    """Set up Amber Express from a config entry."""
    runtime_data = AmberRuntimeData()
    entry.runtime_data = runtime_data

    # Migrate legacy subentry data
    legacy_pricing_modes = {"aemo": PRICING_MODE_AEMO, "app": PRICING_MODE_APP}
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        updated_data: dict | None = None

        current_mode = subentry.data.get(CONF_PRICING_MODE)
        if current_mode in legacy_pricing_modes:
            updated_data = dict(subentry.data)
            updated_data[CONF_PRICING_MODE] = legacy_pricing_modes[current_mode]

        if CONF_FORECAST_INTERVALS not in subentry.data:
            if updated_data is None:
                updated_data = dict(subentry.data)
            updated_data[CONF_FORECAST_INTERVALS] = DEFAULT_FORECAST_INTERVALS

        if updated_data is not None:
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

    # Store site runtime data
    site_data = SiteRuntimeData(
        coordinator=coordinator,
        websocket_client=websocket_client,
    )
    runtime_data.sites[subentry_id] = site_data

    # Start the coordinator (initial fetch + polling lifecycle)
    await coordinator.start()

    # Start WebSocket client if enabled
    if websocket_client:
        await websocket_client.start()

    _LOGGER.debug("Site %s set up successfully", subentry.title)


async def _teardown_site(site_data: SiteRuntimeData) -> None:
    """Tear down a single site."""
    # Stop the coordinator polling lifecycle
    await site_data.coordinator.stop()

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
            await _teardown_site(site_data)
        entry.runtime_data = None

    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: AmberConfigEntry) -> None:
    """Handle options update or subentry changes."""
    _LOGGER.info("Amber Express configuration changed, reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
