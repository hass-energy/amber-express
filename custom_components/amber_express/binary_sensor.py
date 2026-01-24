"""Binary sensor platform for Amber Express integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DESCRIPTOR,
    ATTR_SPIKE_STATUS,
    CHANNEL_GENERAL,
    CONF_ENABLE_GENERAL,
    CONF_SITE_ID,
    DEFAULT_ENABLE_GENERAL,
    DOMAIN,
)
from .coordinator import AmberDataCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express binary sensors."""
    coordinator: AmberDataCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[BinarySensorEntity] = []

    # Only add sensors if general channel is enabled
    if entry.options.get(CONF_ENABLE_GENERAL, DEFAULT_ENABLE_GENERAL):
        entities.append(
            AmberPriceSpikeSensor(
                coordinator=coordinator,
                entry=entry,
            )
        )
        entities.append(
            AmberDemandWindowSensor(
                coordinator=coordinator,
                entry=entry,
            )
        )

    async_add_entities(entities)


class AmberPriceSpikeSensor(CoordinatorEntity[AmberDataCoordinator], BinarySensorEntity):
    """Binary sensor for price spike detection."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the price spike sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._site_id = entry.data[CONF_SITE_ID]
        self._site_name = entry.title
        self._attr_unique_id = f"{self._site_id}_price_spike"
        self._attr_name = f"{self._site_name} - Price Spike"

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

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the demand window sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._site_id = entry.data[CONF_SITE_ID]
        self._site_name = entry.title
        self._attr_unique_id = f"{self._site_id}_demand_window"
        self._attr_name = f"{self._site_name} - Demand Window"

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
