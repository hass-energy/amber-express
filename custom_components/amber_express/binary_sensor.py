"""Binary sensor platform for Amber Express integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DESCRIPTOR,
    ATTR_SPIKE_STATUS,
    CHANNEL_GENERAL,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DOMAIN,
    SUBENTRY_TYPE_SITE,
)
from .coordinator import AmberDataCoordinator
from .interval_processor import CHANNEL_TYPE_MAP

if TYPE_CHECKING:
    from . import AmberConfigEntry

PRICE_SPIKE_ICONS = {
    "none": "mdi:power-plug",
    "potential": "mdi:power-plug-outline",
    "spike": "mdi:power-plug-off",
}


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: AmberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express binary sensors for all site subentries."""
    if not entry.runtime_data:
        return

    # Create and add sensors for each site subentry separately
    # This allows Home Assistant to associate entities with their subentry
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        site_data = entry.runtime_data.sites.get(subentry.subentry_id)
        if not site_data:
            continue

        entities: list[BinarySensorEntity] = []
        coordinator = site_data.coordinator
        _add_site_binary_sensors(entities, coordinator, entry, subentry)

        # Add entities with their subentry ID so devices are associated correctly
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


def _add_site_binary_sensors(
    entities: list[BinarySensorEntity],
    coordinator: AmberDataCoordinator,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
) -> None:
    """Add binary sensors for a single site."""
    # Get available channels from site info
    site_info = coordinator.get_site_info()
    site_channels = site_info.get("channels", [])

    # Check if general channel is available
    has_general = any(CHANNEL_TYPE_MAP.get(ch.get("type")) == CHANNEL_GENERAL for ch in site_channels)

    # Only add sensors if general channel is available
    if has_general:
        entities.append(
            AmberPriceSpikeSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
            )
        )
        entities.append(
            AmberDemandWindowSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
            )
        )


class AmberPriceSpikeSensor(CoordinatorEntity[AmberDataCoordinator], BinarySensorEntity):
    """Binary sensor for price spike detection."""

    _attr_has_entity_name = True
    _attr_translation_key = "price_spike"

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the price spike sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._subentry = subentry
        self._site_id = subentry.data[CONF_SITE_ID]
        self._site_name = subentry.data.get(CONF_SITE_NAME, subentry.title)
        self._attr_unique_id = f"{self._site_id}_price_spike"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._site_id)},
            name=f"Amber Express - {self._site_name}",
            manufacturer="Amber Electric",
            configuration_url="https://app.amber.com.au",
        )

    @property
    def icon(self) -> str:
        """Return the sensor icon based on spike status."""
        channel_data = self.coordinator.get_channel_data(CHANNEL_GENERAL)
        if channel_data:
            status = channel_data.get(ATTR_SPIKE_STATUS) or "none"
            return PRICE_SPIKE_ICONS.get(status, PRICE_SPIKE_ICONS["none"])
        return PRICE_SPIKE_ICONS["none"]

    @property
    def is_on(self) -> bool | None:
        """Return True if there's a price spike."""
        return self.coordinator.is_price_spike()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        channel_data = self.coordinator.get_channel_data(CHANNEL_GENERAL)
        if not channel_data:
            return {}

        return {
            ATTR_SPIKE_STATUS: channel_data.get(ATTR_SPIKE_STATUS),
            ATTR_DESCRIPTOR: channel_data.get(ATTR_DESCRIPTOR),
            "data_source": self.coordinator.data_source,
        }


class AmberDemandWindowSensor(CoordinatorEntity[AmberDataCoordinator], BinarySensorEntity):
    """Binary sensor for demand window detection."""

    _attr_has_entity_name = True
    _attr_translation_key = "demand_window"

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the demand window sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._subentry = subentry
        self._site_id = subentry.data[CONF_SITE_ID]
        self._site_name = subentry.data.get(CONF_SITE_NAME, subentry.title)
        self._attr_unique_id = f"{self._site_id}_demand_window"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._site_id)},
            name=f"Amber Express - {self._site_name}",
            manufacturer="Amber Electric",
            configuration_url="https://app.amber.com.au",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if demand window is active."""
        return self.coordinator.is_demand_window()
