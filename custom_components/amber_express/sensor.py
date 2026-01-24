"""Sensor platform for Amber Express integration."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DESCRIPTOR,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_NEM_TIME,
    ATTR_PER_KWH,
    ATTR_SPIKE_STATUS,
    ATTR_SPOT_PER_KWH,
    ATTR_START_TIME,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_ENABLE_CONTROLLED_LOAD,
    CONF_ENABLE_FEED_IN,
    CONF_ENABLE_GENERAL,
    CONF_SITE_ID,
    DEFAULT_ENABLE_CONTROLLED_LOAD,
    DEFAULT_ENABLE_FEED_IN,
    DEFAULT_ENABLE_GENERAL,
    DOMAIN,
)
from .coordinator import AmberDataCoordinator

CHANNEL_NAMES = {
    CHANNEL_GENERAL: "General",
    CHANNEL_FEED_IN: "Feed In",
    CHANNEL_CONTROLLED_LOAD: "Controlled Load",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express sensors."""
    coordinator: AmberDataCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SensorEntity] = []

    # Determine which channels to enable
    channels_config = {
        CHANNEL_GENERAL: entry.options.get(CONF_ENABLE_GENERAL, DEFAULT_ENABLE_GENERAL),
        CHANNEL_FEED_IN: entry.options.get(CONF_ENABLE_FEED_IN, DEFAULT_ENABLE_FEED_IN),
        CHANNEL_CONTROLLED_LOAD: entry.options.get(CONF_ENABLE_CONTROLLED_LOAD, DEFAULT_ENABLE_CONTROLLED_LOAD),
    }

    for channel, enabled in channels_config.items():
        if enabled:
            # Price sensor
            entities.append(
                AmberPriceSensor(
                    coordinator=coordinator,
                    entry=entry,
                    channel=channel,
                )
            )

            # Forecast sensor (HAEO-compatible)
            entities.append(
                AmberForecastSensor(
                    coordinator=coordinator,
                    entry=entry,
                    channel=channel,
                )
            )

            # Descriptor sensor
            entities.append(
                AmberDescriptorSensor(
                    coordinator=coordinator,
                    entry=entry,
                    channel=channel,
                )
            )

    # Renewables sensor (global)
    if channels_config.get(CHANNEL_GENERAL):
        entities.append(
            AmberRenewablesSensor(
                coordinator=coordinator,
                entry=entry,
            )
        )

        # Tariff sensor (global)
        entities.append(
            AmberTariffSensor(
                coordinator=coordinator,
                entry=entry,
            )
        )

    async_add_entities(entities)


class AmberBaseSensor(CoordinatorEntity[AmberDataCoordinator], SensorEntity):
    """Base class for Amber Express sensors."""

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        channel: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._channel = channel
        self._site_id = entry.data[CONF_SITE_ID]
        self._site_name = entry.title

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._site_id)},
            name=f"Amber Express - {self._site_name}",
            manufacturer="Amber Electric",
            configuration_url="https://app.amber.com.au",
        )


class AmberPriceSensor(AmberBaseSensor):
    """Sensor for current electricity price."""

    # Note: We don't use device_class=MONETARY as it restricts state_class
    # The official Amber integration uses MEASUREMENT without MONETARY device_class
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 2
    _channel: str  # Override type to be non-optional

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        channel: str,
    ) -> None:
        """Initialize the price sensor."""
        super().__init__(coordinator, entry, channel)
        self._channel = channel  # Explicitly set as str
        channel_name = CHANNEL_NAMES.get(channel, channel)
        self._attr_unique_id = f"{self._site_id}_{channel}_price"
        self._attr_name = f"{self._site_name} - {channel_name} Price"

    @property
    def native_value(self) -> float | None:
        """Return the current price."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if channel_data:
            price = channel_data.get(ATTR_PER_KWH)
            if price is None:
                return None
            # Feed-in prices are negated (earnings shown as negative cost)
            # This matches the official Amber Electric integration behavior
            if self._channel == CHANNEL_FEED_IN:
                return price * -1
            return price
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return {}

        attrs = {
            ATTR_START_TIME: channel_data.get(ATTR_START_TIME),
            ATTR_END_TIME: channel_data.get(ATTR_END_TIME),
            ATTR_NEM_TIME: channel_data.get(ATTR_NEM_TIME),
            ATTR_SPOT_PER_KWH: channel_data.get(ATTR_SPOT_PER_KWH),
            ATTR_ESTIMATE: channel_data.get(ATTR_ESTIMATE),
            ATTR_DESCRIPTOR: channel_data.get(ATTR_DESCRIPTOR),
            ATTR_SPIKE_STATUS: channel_data.get(ATTR_SPIKE_STATUS),
            "data_source": self.coordinator.data_source,
        }

        # Include advanced price if available
        if ATTR_ADVANCED_PRICE in channel_data:
            attrs[ATTR_ADVANCED_PRICE] = channel_data[ATTR_ADVANCED_PRICE]

        return {k: v for k, v in attrs.items() if v is not None}


class AmberForecastSensor(AmberBaseSensor):
    """Sensor for electricity price forecasts - HAEO compatible."""

    # Match official Amber integration - no MONETARY device_class
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 2
    _channel: str  # Override type to be non-optional

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        channel: str,
    ) -> None:
        """Initialize the forecast sensor."""
        super().__init__(coordinator, entry, channel)
        self._channel = channel  # Explicitly set as str
        channel_name = CHANNEL_NAMES.get(channel, channel)
        self._attr_unique_id = f"{self._site_id}_{channel}_forecast"
        self._attr_name = f"{self._site_name} - {channel_name} Forecast"

    @property
    def native_value(self) -> float | None:
        """Return the first forecast price (for display)."""
        forecasts = self.coordinator.get_forecasts(self._channel)
        if forecasts:
            price = forecasts[0].get(ATTR_PER_KWH)
            if price is None:
                return None
            # Feed-in prices are negated (matches official Amber integration)
            if self._channel == CHANNEL_FEED_IN:
                return price * -1
            return price
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return HAEO-compatible forecast attributes."""
        forecasts = self.coordinator.get_forecasts(self._channel)

        # For feed-in, invert prices (matches official Amber integration)
        if self._channel == CHANNEL_FEED_IN:
            processed_forecasts = []
            for f in forecasts:
                processed = f.copy()
                if ATTR_PER_KWH in processed and processed[ATTR_PER_KWH] is not None:
                    processed[ATTR_PER_KWH] = processed[ATTR_PER_KWH] * -1
                processed_forecasts.append(processed)
            forecasts = processed_forecasts

        return {
            ATTR_FORECASTS: forecasts,
            "data_source": self.coordinator.data_source,
        }


class AmberDescriptorSensor(AmberBaseSensor):
    """Sensor for price descriptor."""

    _channel: str  # Override type to be non-optional

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        channel: str,
    ) -> None:
        """Initialize the descriptor sensor."""
        super().__init__(coordinator, entry, channel)
        self._channel = channel  # Explicitly set as str
        channel_name = CHANNEL_NAMES.get(channel, channel)
        self._attr_unique_id = f"{self._site_id}_{channel}_descriptor"
        self._attr_name = f"{self._site_name} - {channel_name} Price Descriptor"

    @property
    def native_value(self) -> str | None:
        """Return the price descriptor."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if channel_data:
            return channel_data.get(ATTR_DESCRIPTOR)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return {}

        return {
            ATTR_SPIKE_STATUS: channel_data.get(ATTR_SPIKE_STATUS),
        }


class AmberRenewablesSensor(AmberBaseSensor):
    """Sensor for grid renewables percentage."""

    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the renewables sensor."""
        super().__init__(coordinator, entry, None)
        self._attr_unique_id = f"{self._site_id}_renewables"
        self._attr_name = f"{self._site_name} - Renewables"

    @property
    def native_value(self) -> float | None:
        """Return the renewables percentage."""
        return self.coordinator.get_renewables()


class AmberTariffSensor(AmberBaseSensor):
    """Sensor for current tariff/channel information."""

    # Friendly names for channels
    CHANNEL_FRIENDLY_NAMES: ClassVar[dict[str, str]] = {
        CHANNEL_GENERAL: "General",
        CHANNEL_FEED_IN: "Feed In",
        CHANNEL_CONTROLLED_LOAD: "Controlled Load",
        "general": "General",
        "feedIn": "Feed In",
        "controlledLoad": "Controlled Load",
    }

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the tariff sensor."""
        super().__init__(coordinator, entry, None)
        self._attr_unique_id = f"{self._site_id}_tariff"
        self._attr_name = f"{self._site_name} - Tariff"

    @property
    def native_value(self) -> str | None:
        """Return the network name as the state."""
        site_info = self.coordinator.get_site_info()
        return site_info.get("network")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return tariff and channel details as attributes."""
        attrs: dict[str, Any] = {}
        site_info = self.coordinator.get_site_info()

        # Network and NMI
        if site_info.get("network"):
            attrs["network"] = site_info["network"]
        if site_info.get("nmi"):
            attrs["nmi"] = site_info["nmi"]
        if site_info.get("status"):
            attrs["status"] = site_info["status"]
        if site_info.get("interval_length"):
            attrs["interval_length"] = site_info["interval_length"]

        # Tariff codes from site info (e.g., EA116, EA029)
        site_channels = site_info.get("channels", [])
        tariffs: list[dict[str, Any]] = []
        for ch in site_channels:
            tariff_entry = {
                "type": ch.get("type"),
                "type_name": self.CHANNEL_FRIENDLY_NAMES.get(ch.get("type"), ch.get("type")),
                "tariff_code": ch.get("tariff"),
                "identifier": ch.get("identifier"),
            }
            tariffs.append(tariff_entry)

        attrs["tariffs"] = tariffs
        attrs["tariff_count"] = len(tariffs)

        # Extract just the tariff codes for easy access
        tariff_codes = [ch.get("tariff") for ch in site_channels if ch.get("tariff")]
        attrs["tariff_codes"] = tariff_codes

        # Active channels from current data
        active_channels = self.coordinator.get_active_channels()
        attrs["active_channels"] = active_channels

        # Individual channel flags
        attrs["has_general"] = any(ch.get("type") == "general" for ch in site_channels)
        attrs["has_feed_in"] = any(ch.get("type") == "feedIn" for ch in site_channels)
        attrs["has_controlled_load"] = any(ch.get("type") == "controlledLoad" for ch in site_channels)

        # TOU/demand tariff info from current interval
        tariff_info = self.coordinator.get_tariff_info()
        if tariff_info.get("period"):
            attrs["period"] = tariff_info["period"]
        if tariff_info.get("season"):
            attrs["season"] = tariff_info["season"]
        if tariff_info.get("block") is not None:
            attrs["block"] = tariff_info["block"]
        if tariff_info.get("demand_window") is not None:
            attrs["demand_window"] = tariff_info["demand_window"]

        attrs["data_source"] = self.coordinator.data_source

        return attrs
