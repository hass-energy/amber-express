"""Select platform for Amber Express integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DEFAULT_PRICING_MODE,
    DOMAIN,
    PRICING_MODE_AEMO,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from .coordinator import AmberDataCoordinator

if TYPE_CHECKING:
    from . import AmberConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express select entities for all site subentries."""
    if not entry.runtime_data:
        return

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        site_data = entry.runtime_data.sites.get(subentry.subentry_id)
        if not site_data:
            continue

        entities: list[SelectEntity] = [
            PricingModeSelect(hass, entry, subentry, site_data.coordinator),
        ]

        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


class PricingModeSelect(SelectEntity):
    """Select entity for pricing mode configuration."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "pricing_mode"
    _attr_options: ClassVar[list[str]] = [PRICING_MODE_APP, PRICING_MODE_AEMO]

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        coordinator: AmberDataCoordinator,
    ) -> None:
        """Initialize the pricing mode select."""
        self._hass = hass
        self._entry = entry
        self._subentry = subentry
        self._coordinator = coordinator
        self._site_id = subentry.data[CONF_SITE_ID]
        self._site_name = subentry.data.get(CONF_SITE_NAME, subentry.title)
        self._attr_unique_id = f"{self._site_id}_pricing_mode"

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
    def current_option(self) -> str:
        """Return the current pricing mode (reads fresh from config entry)."""
        subentry = self._entry.subentries.get(self._subentry.subentry_id)
        if subentry is None:
            return DEFAULT_PRICING_MODE
        return subentry.data.get(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)

    async def async_select_option(self, option: str) -> None:
        """Change the pricing mode."""
        if option not in self._attr_options:
            return

        # Update subentry data with new pricing mode
        updated_data = dict(self._subentry.data)
        updated_data[CONF_PRICING_MODE] = option

        self._hass.config_entries.async_update_subentry(
            self._entry,
            self._subentry,
            data=updated_data,
        )

        # Update coordinator's interval processor and refresh data
        self._coordinator.update_pricing_mode(option)
        await self._coordinator.async_refresh()
