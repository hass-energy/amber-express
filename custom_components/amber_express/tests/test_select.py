"""Tests for select platform."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.const import (
    CONF_API_TOKEN,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DOMAIN,
    PRICING_MODE_AEMO,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from custom_components.amber_express.select import PricingModeSelect


def _create_subentry(pricing_mode: str = PRICING_MODE_APP) -> MagicMock:
    """Create a mock site subentry."""
    subentry = MagicMock()
    subentry.subentry_type = SUBENTRY_TYPE_SITE
    subentry.subentry_id = "test_subentry_id"
    subentry.title = "Test Site"
    subentry.data = {
        CONF_SITE_ID: "test_site",
        CONF_SITE_NAME: "Test Site",
        CONF_PRICING_MODE: pricing_mode,
    }
    return subentry


def _create_entry(hass: HomeAssistant, subentry: MagicMock) -> MockConfigEntry:
    """Create a mock config entry containing one site subentry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Amber Electric",
        data={CONF_API_TOKEN: "test_token"},
    )
    entry.subentries = {"test_subentry_id": subentry}
    entry.add_to_hass(hass)
    return entry


async def test_pricing_mode_select_excludes_removed_both_option(hass: HomeAssistant) -> None:
    """Test pricing mode select exposes only APP and AEMO options."""
    subentry = _create_subentry()
    entry = _create_entry(hass, subentry)
    coordinator = MagicMock()

    entity = PricingModeSelect(hass, entry, subentry, coordinator)

    assert entity._attr_options == [PRICING_MODE_APP, PRICING_MODE_AEMO]
    assert "all" not in entity._attr_options


async def test_pricing_mode_select_updates_valid_option(hass: HomeAssistant) -> None:
    """Test selecting a valid pricing mode updates subentry and coordinator."""
    subentry = _create_subentry(pricing_mode=PRICING_MODE_AEMO)
    entry = _create_entry(hass, subentry)
    coordinator = MagicMock()
    coordinator.update_pricing_mode = MagicMock()
    coordinator.async_refresh = AsyncMock()
    hass.config_entries.async_update_subentry = MagicMock()

    entity = PricingModeSelect(hass, entry, subentry, coordinator)

    await entity.async_select_option(PRICING_MODE_APP)

    coordinator.update_pricing_mode.assert_called_once_with(PRICING_MODE_APP)
    coordinator.async_refresh.assert_awaited_once()
    hass.config_entries.async_update_subentry.assert_called_once()
