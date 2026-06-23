"""Sensor platform for Amber Express integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DESCRIPTOR,
    ATTR_DETAILED_FORECAST,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECAST,
    ATTR_PER_KWH,
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
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from .coordinator import AmberDataCoordinator
from .data import CHANNEL_TYPE_MAP
from .types import ChannelData
from .utils import get_http_status_label, to_local_iso_minute

if TYPE_CHECKING:
    from . import AmberConfigEntry

CHANNEL_PRICE_TRANSLATION_KEY = {
    CHANNEL_GENERAL: "general_price",
    CHANNEL_FEED_IN: "feed_in_price",
    CHANNEL_CONTROLLED_LOAD: "controlled_load_price",
}


# ---------------------------------------------------------------------------
# Entity description for description-driven sensors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class AmberSensorDescription(SensorEntityDescription):
    """Describes an Amber Express sensor entity."""

    value_fn: Callable[[AmberDataCoordinator], Any]
    attributes_fn: Callable[[AmberDataCoordinator], dict[str, Any]] | None = None


def _site_attributes(coordinator: AmberDataCoordinator) -> dict[str, Any]:
    """Return site info as attributes."""
    site = coordinator.get_site_info()
    return {
        "id": site.id,
        "nmi": site.nmi,
        "network": site.network,
        "status": site.status.value,
        "interval_length": site.interval_length,
        "channels": [{"identifier": ch.identifier, "type": ch.type.value, "tariff": ch.tariff} for ch in site.channels],
    }


def _api_status_attributes(coordinator: AmberDataCoordinator) -> dict[str, Any]:
    """Return API status details and rate limit info as attributes."""
    rate_limit = coordinator.get_rate_limit_info()
    return {
        "status_code": coordinator.get_api_status(),
        "rate_limit_quota": rate_limit.get("limit"),
        "rate_limit_remaining": rate_limit.get("remaining"),
        "rate_limit_reset_at": rate_limit.get("reset_at").isoformat() if rate_limit.get("reset_at") else None,
        "rate_limit_window_seconds": rate_limit.get("window_seconds"),
        "rate_limit_policy": rate_limit.get("policy"),
    }


def _next_poll_attributes(coordinator: AmberDataCoordinator) -> dict[str, Any]:
    """Return poll schedule as attributes."""
    stats = coordinator.get_cdf_polling_stats()
    return {
        "poll_schedule": [round(t, 1) for t in stats.scheduled_polls],
        "poll_count": stats.confirmatory_poll_count + 1,
    }


def _confirmation_delay_value(coordinator: AmberDataCoordinator) -> float | None:
    """Return the last time-to-confirmed value in seconds."""
    stats = coordinator.get_cdf_polling_stats()
    if stats.last_observation is not None:
        return stats.last_observation["end"]
    return None


def _confirmation_lag_value(coordinator: AmberDataCoordinator) -> float | None:
    """Return the time gap between estimate and confirmed polls."""
    stats = coordinator.get_cdf_polling_stats()
    if stats.last_observation is not None:
        return stats.last_observation["end"] - stats.last_observation["start"]
    return None


SENSOR_DESCRIPTIONS: tuple[AmberSensorDescription, ...] = (
    AmberSensorDescription(
        key="renewables",
        translation_key="renewables",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=lambda c: c.get_renewables(),
    ),
    AmberSensorDescription(
        key="site",
        translation_key="site",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.get_site_info().network,
        attributes_fn=_site_attributes,
    ),
    AmberSensorDescription(
        key="confirmation_delay",
        translation_key="confirmation_delay",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="s",
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_confirmation_delay_value,
    ),
    AmberSensorDescription(
        key="confirmation_lag",
        translation_key="confirmation_lag",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="s",
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_confirmation_lag_value,
    ),
    AmberSensorDescription(
        key="api_status",
        translation_key="api_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: get_http_status_label(c.get_api_status()),
        attributes_fn=_api_status_attributes,
    ),
    AmberSensorDescription(
        key="rate_limit_remaining",
        translation_key="rate_limit_remaining",
        native_unit_of_measurement="requests",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.get_rate_limit_info().get("remaining"),
    ),
    AmberSensorDescription(
        key="rate_limit_reset",
        translation_key="rate_limit_reset",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.get_rate_limit_info().get("reset_at"),
    ),
    AmberSensorDescription(
        key="next_poll",
        translation_key="next_poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.get_next_poll_time(),
        attributes_fn=_next_poll_attributes,
    ),
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: AmberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express sensors for all site subentries."""
    if not entry.runtime_data:
        return

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        site_data = entry.runtime_data.sites.get(subentry.subentry_id)
        if not site_data:
            continue

        entities: list[SensorEntity] = []
        coordinator = site_data.coordinator
        _add_site_sensors(entities, coordinator, entry, subentry)

        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


def _add_site_sensors(
    entities: list[SensorEntity],
    coordinator: AmberDataCoordinator,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
) -> None:
    """Add sensors for a single site."""
    site = coordinator.get_site_info()

    available_channels: set[str] = set()
    for ch in site.channels:
        api_type = ch.type.value
        if api_type in CHANNEL_TYPE_MAP:
            available_channels.add(CHANNEL_TYPE_MAP[api_type])

    entities.extend(
        AmberPriceSensor(
            coordinator=coordinator,
            entry=entry,
            subentry=subentry,
            channel=channel,
        )
        for channel in available_channels
    )

    if available_channels:
        entities.extend(
            AmberSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
                description=description,
            )
            for description in SENSOR_DESCRIPTIONS
        )

        entities.append(
            AmberForecastHorizonSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
            )
        )


# ---------------------------------------------------------------------------
# Base sensor
# ---------------------------------------------------------------------------


class AmberBaseSensor(CoordinatorEntity[AmberDataCoordinator], SensorEntity):
    """Base class for Amber Express sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._subentry = subentry
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


# ---------------------------------------------------------------------------
# Description-driven sensor (handles all simple sensors)
# ---------------------------------------------------------------------------


class AmberSensor(AmberBaseSensor):
    """Generic sensor driven by an AmberSensorDescription."""

    entity_description: AmberSensorDescription

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        description: AmberSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self.entity_description = description
        self._attr_unique_id = f"{self._site_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.entity_description.attributes_fn:
            return self.entity_description.attributes_fn(self.coordinator)
        return None


# ---------------------------------------------------------------------------
# Price sensors (shared logic via base class)
# ---------------------------------------------------------------------------


class AmberPriceSensor(AmberBaseSensor):
    """Sensor for current electricity price."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 2
    _unrecorded_attributes = frozenset({ATTR_DETAILED_FORECAST})

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        channel: str,
    ) -> None:
        """Initialize the price sensor."""
        super().__init__(coordinator, entry, subentry)
        self._channel = channel
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

        if price_key == ATTR_ADVANCED_PRICE and isinstance(price, dict):
            price = price.get("predicted")

        if price is None and price_key == ATTR_ADVANCED_PRICE:
            price = data.get(ATTR_PER_KWH)

        if price is None:
            return None
        if not isinstance(price, int | float):
            return None

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
        if self._channel == CHANNEL_GENERAL and channel_data.get(ATTR_DEMAND_WINDOW):
            demand_window_price = self._get_subentry_option(CONF_DEMAND_WINDOW_PRICE, DEFAULT_DEMAND_WINDOW_PRICE)
            price += demand_window_price
        return price

    def _negate_prices(self, data: ChannelData) -> dict[str, Any]:
        """Negate price fields for the feed-in channel."""
        result: dict[str, Any] = dict(data)
        for key in (ATTR_PER_KWH, ATTR_ADVANCED_PRICE):
            if key not in result:
                continue
            value = result[key]
            if isinstance(value, int | float):
                result[key] = value * -1
            elif isinstance(value, dict):
                result[key] = {k: v * -1 for k, v in value.items()}
        return result

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return {}

        attrs: dict[str, Any] = {
            ATTR_START_TIME: to_local_iso_minute(channel_data.get(ATTR_START_TIME)),
            ATTR_END_TIME: to_local_iso_minute(channel_data.get(ATTR_END_TIME)),
            ATTR_ESTIMATE: channel_data.get(ATTR_ESTIMATE),
            ATTR_DESCRIPTOR: channel_data.get(ATTR_DESCRIPTOR),
            "data_source": self.coordinator.data_source,
        }

        forecasts = self.coordinator.get_forecasts(self._channel)
        forecast_list: list[dict[str, Any]] = []
        demand_window_price = self._get_subentry_option(CONF_DEMAND_WINDOW_PRICE, DEFAULT_DEMAND_WINDOW_PRICE)
        for f in forecasts:
            time_value = to_local_iso_minute(f.get(ATTR_START_TIME))
            value = self._get_price(f, self._get_price_key())
            if value is not None and self._channel == CHANNEL_GENERAL and f.get(ATTR_DEMAND_WINDOW):
                value += demand_window_price
            forecast_list.append({"time": time_value, "value": value})
        attrs["interpolation_mode"] = "previous"
        attrs[ATTR_FORECAST] = forecast_list

        if self._channel == CHANNEL_FEED_IN:
            attrs[ATTR_DETAILED_FORECAST] = [self._negate_prices(f) for f in forecasts]
        else:
            attrs[ATTR_DETAILED_FORECAST] = list(forecasts)

        return {k: v for k, v in attrs.items() if v is not None}


# ---------------------------------------------------------------------------
# Forecast horizon sensor
# ---------------------------------------------------------------------------


class AmberForecastHorizonSensor(AmberBaseSensor):
    """Sensor for how many hours of forecast data are available."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "h"
    _attr_suggested_display_precision = 0
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _FORECAST_CHANNELS: tuple[str, ...] = (
        CHANNEL_GENERAL,
        CHANNEL_FEED_IN,
        CHANNEL_CONTROLLED_LOAD,
    )

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the forecast horizon sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_forecast_horizon"
        self._attr_translation_key = "forecast_horizon"

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        """Parse an ISO timestamp string into a datetime."""
        if not isinstance(value, str):
            return None
        return dt_util.parse_datetime(value)

    def _get_latest_forecast_end(self) -> datetime | None:
        """Return the latest forecast end_time across all channels."""
        latest_end: datetime | None = None
        for channel in self._FORECAST_CHANNELS:
            for forecast in self.coordinator.get_forecasts(channel):
                end_time = self._parse_datetime(forecast.get(ATTR_END_TIME))
                if end_time is None:
                    continue
                if latest_end is None or end_time > latest_end:
                    latest_end = end_time
        return latest_end

    @property
    def native_value(self) -> float | None:
        """Return the forecast horizon in hours."""
        baseline = self.coordinator.get_forecasts_timestamp()
        if baseline is None:
            return None

        latest_end = self._get_latest_forecast_end()
        if latest_end is None:
            return None

        return (latest_end - baseline).total_seconds() / 3600

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the raw forecast end timestamp as an attribute."""
        latest_end = self._get_latest_forecast_end()
        if latest_end is None:
            return {}
        return {"forecast_end": latest_end.isoformat()}
