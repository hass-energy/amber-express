"""Sensor platform for Amber Express integration."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DESCRIPTOR,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_SPOT_PER_KWH,
    ATTR_START_TIME,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_DEMAND_WINDOW_PRICE,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DEFAULT_DEMAND_WINDOW_PRICE,
    DEFAULT_PRICING_MODE,
    DOMAIN,
    PRICING_MODE_ALL,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from .coordinator import AmberDataCoordinator
from .interval_processor import CHANNEL_TYPE_MAP
from .types import ChannelData
from .utils import to_local_iso

if TYPE_CHECKING:
    from . import AmberConfigEntry

# Map channel to translation key for price sensors
CHANNEL_PRICE_TRANSLATION_KEY = {
    CHANNEL_GENERAL: "general_price",
    CHANNEL_FEED_IN: "feed_in_price",
    CHANNEL_CONTROLLED_LOAD: "controlled_load_price",
}

# Map channel to translation key for detailed price sensors
CHANNEL_PRICE_DETAILED_TRANSLATION_KEY = {
    CHANNEL_GENERAL: "general_price_detailed",
    CHANNEL_FEED_IN: "feed_in_price_detailed",
    CHANNEL_CONTROLLED_LOAD: "controlled_load_price_detailed",
}


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: AmberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express sensors for all site subentries."""
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

        entities: list[SensorEntity] = []
        coordinator = site_data.coordinator
        _add_site_sensors(entities, coordinator, entry, subentry)

        # Add entities with their subentry ID so devices are associated correctly
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


def _add_site_sensors(
    entities: list[SensorEntity],
    coordinator: AmberDataCoordinator,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
) -> None:
    """Add sensors for a single site."""
    # Get available channels from site info
    site_info = coordinator.get_site_info()
    site_channels = site_info.get("channels", [])

    # Map API channel types to internal channel constants
    available_channels: set[str] = set()
    for ch in site_channels:
        api_type = ch.get("type")
        if api_type and api_type in CHANNEL_TYPE_MAP:
            available_channels.add(CHANNEL_TYPE_MAP[api_type])

    # Create sensors for each available channel
    for channel in available_channels:
        # Price sensor
        entities.append(
            AmberPriceSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
                channel=channel,
            )
        )

        # Detailed price sensor (disabled by default)
        entities.append(
            AmberDetailedPriceSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
                channel=channel,
            )
        )

    # Global sensors (always created if we have any channels)
    if available_channels:
        # Renewables sensor
        entities.append(
            AmberRenewablesSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
            )
        )

        # Site sensor
        entities.append(
            AmberSiteSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
            )
        )

        # Polling stats sensor
        entities.append(
            AmberPollingStatsSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
            )
        )

        # API error sensor
        entities.append(
            AmberApiStatusSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
            )
        )


class AmberBaseSensor(CoordinatorEntity[AmberDataCoordinator], SensorEntity):
    """Base class for Amber Express sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        channel: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._subentry = subentry
        self._channel = channel
        self._site_id = subentry.data[CONF_SITE_ID]
        self._site_name = subentry.data.get(CONF_SITE_NAME, subentry.title)

    def _get_subentry_option(self, key: str, default: Any) -> Any:
        """Get an option from subentry data (reads fresh from config entry)."""
        subentry = self._entry.subentries.get(self._subentry.subentry_id)
        if subentry is None:
            return default
        return subentry.data.get(key, default)

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
        subentry: ConfigSubentry,
        channel: str,
    ) -> None:
        """Initialize the price sensor."""
        super().__init__(coordinator, entry, subentry, channel)
        self._channel = channel  # Explicitly set as str
        self._attr_unique_id = f"{self._site_id}_{channel}_price"
        self._attr_translation_key = CHANNEL_PRICE_TRANSLATION_KEY.get(channel, "general_price")

    def _get_price_key(self) -> str:
        """Return the price key based on configured pricing mode."""
        pricing_mode = self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)
        if pricing_mode == PRICING_MODE_APP:
            return ATTR_ADVANCED_PRICE
        return ATTR_PER_KWH

    def _get_price(self, data: ChannelData, price_key: str) -> float | None:
        """Extract price from data, with fallback and feed-in negation."""
        price = data.get(price_key)

        # Handle advanced_price_predicted which is a dict with low/predicted/high
        if price_key == ATTR_ADVANCED_PRICE and isinstance(price, dict):
            price = price.get("predicted")

        # Fall back to per_kwh if advanced price not available
        if price is None and price_key == ATTR_ADVANCED_PRICE:
            price = data.get(ATTR_PER_KWH)

        if price is None:
            return None
        if not isinstance(price, int | float):
            return None

        # Feed-in prices are negated (earnings shown as negative cost)
        if self._channel == CHANNEL_FEED_IN:
            return price * -1
        return price

    @property
    def native_value(self) -> float | None:
        """Return the current price."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return None
        price = self._get_price(channel_data, self._get_price_key())
        if price is None:
            return None
        # Apply demand window price for general channel
        if self._channel == CHANNEL_GENERAL and channel_data.get(ATTR_DEMAND_WINDOW):
            demand_window_price = self._get_subentry_option(CONF_DEMAND_WINDOW_PRICE, DEFAULT_DEMAND_WINDOW_PRICE)
            price += demand_window_price
        return price

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return {}

        attrs: dict[str, Any] = {
            ATTR_START_TIME: channel_data.get(ATTR_START_TIME),
            ATTR_END_TIME: channel_data.get(ATTR_END_TIME),
            ATTR_ESTIMATE: channel_data.get(ATTR_ESTIMATE),
            ATTR_DESCRIPTOR: channel_data.get(ATTR_DESCRIPTOR),
            "data_source": self.coordinator.data_source,
        }

        # Build simple forecast list for energy optimization tools
        pricing_mode = self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)
        forecasts = self.coordinator.get_forecasts(self._channel)
        forecast_list: list[dict[str, Any]] = []
        demand_window_price = self._get_subentry_option(CONF_DEMAND_WINDOW_PRICE, DEFAULT_DEMAND_WINDOW_PRICE)
        for f in forecasts:
            time_value = to_local_iso(f.get(ATTR_START_TIME))
            if pricing_mode == PRICING_MODE_ALL:
                # Include all price types
                per_kwh = self._get_price(f, ATTR_PER_KWH)
                advanced = self._get_price(f, ATTR_ADVANCED_PRICE)
                # Apply demand window price for general channel
                if self._channel == CHANNEL_GENERAL and f.get(ATTR_DEMAND_WINDOW):
                    if per_kwh is not None:
                        per_kwh += demand_window_price
                    if advanced is not None:
                        advanced += demand_window_price
                forecast_list.append(
                    {
                        "time": time_value,
                        ATTR_PER_KWH: per_kwh,
                        ATTR_ADVANCED_PRICE: advanced,
                    }
                )
            else:
                # Single price value based on mode
                value = self._get_price(f, self._get_price_key())
                if value is not None and self._channel == CHANNEL_GENERAL and f.get(ATTR_DEMAND_WINDOW):
                    value += demand_window_price
                forecast_list.append({"time": time_value, "value": value})
        attrs["forecast"] = forecast_list

        return {k: v for k, v in attrs.items() if v is not None}


class AmberDetailedPriceSensor(AmberBaseSensor):
    """Sensor for electricity price with detailed forecast attributes."""

    # Match official Amber integration - no MONETARY device_class
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False
    _channel: str  # Override type to be non-optional

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        channel: str,
    ) -> None:
        """Initialize the detailed price sensor."""
        super().__init__(coordinator, entry, subentry, channel)
        self._channel = channel  # Explicitly set as str
        self._attr_unique_id = f"{self._site_id}_{channel}_price_detailed"
        self._attr_translation_key = CHANNEL_PRICE_DETAILED_TRANSLATION_KEY.get(channel, "general_price_detailed")

    def _get_price_key(self) -> str:
        """Return the price key based on configured pricing mode."""
        pricing_mode = self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)
        if pricing_mode == PRICING_MODE_APP:
            return ATTR_ADVANCED_PRICE
        return ATTR_PER_KWH

    def _get_price(self, data: ChannelData, price_key: str) -> float | None:
        """Extract price from data, with fallback and feed-in negation."""
        price = data.get(price_key)

        # Handle advanced_price_predicted which is a dict with low/predicted/high
        if price_key == ATTR_ADVANCED_PRICE and isinstance(price, dict):
            price = price.get("predicted")

        # Fall back to per_kwh if advanced price not available
        if price is None and price_key == ATTR_ADVANCED_PRICE:
            price = data.get(ATTR_PER_KWH)

        if price is None:
            return None
        if not isinstance(price, int | float):
            return None

        # Feed-in prices are negated (earnings shown as negative cost)
        if self._channel == CHANNEL_FEED_IN:
            return price * -1
        return price

    @property
    def native_value(self) -> float | None:
        """Return the current price."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return None
        return self._get_price(channel_data, self._get_price_key())

    # Fields to strip from forecasts to reduce payload size
    _FORECAST_STRIP_FIELDS = (
        "tariff_period",
        "tariff_season",
        "tariff_block",
        "nem_time",
        "descriptor",
        "spike_status",
        "estimate",
    )

    def _negate_prices(self, data: dict[str, Any]) -> dict[str, Any]:
        """Negate price fields for feed-in channel."""
        result = data.copy()
        for key in (ATTR_PER_KWH, ATTR_ADVANCED_PRICE, ATTR_SPOT_PER_KWH):
            if key in result and isinstance(result[key], int | float):
                result[key] = result[key] * -1
        return result

    def _strip_forecast_fields(self, forecast: dict[str, Any]) -> dict[str, Any]:
        """Remove wasteful fields from forecast entry."""
        return {k: v for k, v in forecast.items() if k not in self._FORECAST_STRIP_FIELDS}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all channel data as attributes."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return {"data_source": self.coordinator.data_source}

        # Make a copy to avoid mutating the original
        attrs: dict[str, Any] = dict(channel_data)

        # Process forecasts: strip wasteful fields and negate prices for feed-in
        if ATTR_FORECASTS in attrs:
            forecasts = attrs[ATTR_FORECASTS]
            # Strip wasteful fields
            forecasts = [self._strip_forecast_fields(f) for f in forecasts]
            # Negate prices for feed-in
            if self._channel == CHANNEL_FEED_IN:
                forecasts = [self._negate_prices(f) for f in forecasts]
            attrs[ATTR_FORECASTS] = forecasts

        # For feed-in, also negate current interval prices
        if self._channel == CHANNEL_FEED_IN:
            attrs = self._negate_prices(attrs)

        attrs["data_source"] = self.coordinator.data_source
        return attrs


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
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the renewables sensor."""
        super().__init__(coordinator, entry, subentry, None)
        self._attr_unique_id = f"{self._site_id}_renewables"
        self._attr_translation_key = "renewables"

    @property
    def native_value(self) -> float | None:
        """Return the renewables percentage."""
        return self.coordinator.get_renewables()


class AmberSiteSensor(AmberBaseSensor):
    """Sensor for site information."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the site sensor."""
        super().__init__(coordinator, entry, subentry, None)
        self._attr_unique_id = f"{self._site_id}_site"
        self._attr_translation_key = "site"

    @property
    def native_value(self) -> str | None:
        """Return the network name as the state."""
        site_info = self.coordinator.get_site_info()
        return site_info.get("network")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return site info as attributes."""
        return self.coordinator.get_site_info()


class AmberPollingStatsSensor(AmberBaseSensor):
    """Sensor for polling statistics including time-to-confirmed."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "s"
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the polling stats sensor."""
        super().__init__(coordinator, entry, subentry, None)
        self._attr_unique_id = f"{self._site_id}_confirmation_delay"
        self._attr_translation_key = "confirmation_delay"

    @property
    def native_value(self) -> float | None:
        """Return the last time-to-confirmed value in seconds."""
        offset_stats = self.coordinator.get_polling_offset_stats()
        return offset_stats.last_confirmed_elapsed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return polling statistics as attributes."""
        offset_stats = self.coordinator.get_polling_offset_stats()
        attrs: dict[str, Any] = {
            "polling_delay": offset_stats.offset,
            "poll_count": offset_stats.confirmatory_poll_count + 1,
        }

        if offset_stats.last_estimate_elapsed is not None:
            attrs["last_estimate_elapsed"] = round(offset_stats.last_estimate_elapsed, 1)
        if offset_stats.last_confirmed_elapsed is not None:
            attrs["last_confirmed_elapsed"] = round(offset_stats.last_confirmed_elapsed, 1)

        return attrs


class AmberApiStatusSensor(AmberBaseSensor):
    """Sensor for API error status."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the API error sensor."""
        super().__init__(coordinator, entry, subentry, None)
        self._attr_unique_id = f"{self._site_id}_api_status"
        self._attr_translation_key = "api_status"

    @staticmethod
    def _get_http_status_label(status_code: int) -> str:
        """Get human-readable label for HTTP status code."""
        try:
            return HTTPStatus(status_code).phrase
        except ValueError:
            return "Unknown Error"

    @property
    def native_value(self) -> str:
        """Return the API status as human-readable label."""
        return self._get_http_status_label(self.coordinator.get_api_status())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return API status details and rate limit info as attributes."""
        rate_limit = self.coordinator.get_rate_limit_info()
        return {
            "status_code": self.coordinator.get_api_status(),
            "rate_limit_quota": rate_limit.get("limit"),
            "rate_limit_remaining": rate_limit.get("remaining"),
            "rate_limit_reset_seconds": rate_limit.get("reset_seconds"),
            "rate_limit_window_seconds": rate_limit.get("window_seconds"),
            "rate_limit_policy": rate_limit.get("policy"),
        }
