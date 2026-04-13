"""Binary sensor platform for Amber Express integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
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
from .data import CHANNEL_TYPE_MAP

if TYPE_CHECKING:
    from . import AmberConfigEntry

PRICE_SPIKE_ICONS = {
    "none": "mdi:power-plug",
    "potential": "mdi:power-plug-outline",
    "spike": "mdi:power-plug-off",
}


# ---------------------------------------------------------------------------
# Entity description
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class AmberBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Amber Express binary sensor entity."""

    value_fn: Callable[[AmberDataCoordinator], bool | None]
    attributes_fn: Callable[[AmberDataCoordinator], dict[str, Any]] | None = None
    icon_fn: Callable[[AmberDataCoordinator], str] | None = None


def _price_spike_icon(coordinator: AmberDataCoordinator) -> str:
    """Return the icon based on spike status."""
    channel_data = coordinator.get_channel_data(CHANNEL_GENERAL)
    if channel_data:
        status = channel_data.get(ATTR_SPIKE_STATUS) or "none"
        return PRICE_SPIKE_ICONS.get(status, PRICE_SPIKE_ICONS["none"])
    return PRICE_SPIKE_ICONS["none"]


def _price_spike_attributes(coordinator: AmberDataCoordinator) -> dict[str, Any]:
    """Return price spike extra attributes."""
    channel_data = coordinator.get_channel_data(CHANNEL_GENERAL)
    if not channel_data:
        return {}
    return {
        ATTR_SPIKE_STATUS: channel_data.get(ATTR_SPIKE_STATUS),
        ATTR_DESCRIPTOR: channel_data.get(ATTR_DESCRIPTOR),
        "data_source": coordinator.data_source,
    }


BINARY_SENSOR_DESCRIPTIONS: tuple[AmberBinarySensorDescription, ...] = (
    AmberBinarySensorDescription(
        key="price_spike",
        translation_key="price_spike",
        value_fn=lambda c: c.is_price_spike(),
        attributes_fn=_price_spike_attributes,
        icon_fn=_price_spike_icon,
    ),
    AmberBinarySensorDescription(
        key="demand_window",
        translation_key="demand_window",
        value_fn=lambda c: c.is_demand_window(),
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
    """Set up Amber Express binary sensors for all site subentries."""
    if not entry.runtime_data:
        return

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        site_data = entry.runtime_data.sites.get(subentry.subentry_id)
        if not site_data:
            continue

        entities: list[BinarySensorEntity] = []
        coordinator = site_data.coordinator
        _add_site_binary_sensors(entities, coordinator, entry, subentry)

        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


def _add_site_binary_sensors(
    entities: list[BinarySensorEntity],
    coordinator: AmberDataCoordinator,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
) -> None:
    """Add binary sensors for a single site."""
    site = coordinator.get_site_info()

    has_general = any(CHANNEL_TYPE_MAP.get(ch.type.value) == CHANNEL_GENERAL for ch in site.channels)

    if has_general:
        entities.extend(
            AmberBinarySensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
                description=description,
            )
            for description in BINARY_SENSOR_DESCRIPTIONS
        )


# ---------------------------------------------------------------------------
# Generic binary sensor
# ---------------------------------------------------------------------------


class AmberBinarySensor(CoordinatorEntity[AmberDataCoordinator], BinarySensorEntity):
    """Generic binary sensor driven by an AmberBinarySensorDescription."""

    _attr_has_entity_name = True
    entity_description: AmberBinarySensorDescription

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        description: AmberBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._subentry = subentry
        self._site_id = subentry.data[CONF_SITE_ID]
        self._site_name = subentry.data.get(CONF_SITE_NAME, subentry.title)
        self._attr_unique_id = f"{self._site_id}_{description.key}"

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
    def icon(self) -> str | None:
        """Return the sensor icon."""
        if self.entity_description.icon_fn:
            return self.entity_description.icon_fn(self.coordinator)
        return None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.entity_description.attributes_fn:
            return self.entity_description.attributes_fn(self.coordinator)
        return None
