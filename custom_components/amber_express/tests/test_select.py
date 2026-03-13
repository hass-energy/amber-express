"""Tests for select platform."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.const import (
    CONF_API_TOKEN,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DEFAULT_PRICING_MODE,
    DOMAIN,
    PRICING_MODE_AEMO,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from custom_components.amber_express.select import PricingModeSelect, async_setup_entry


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


async def test_pricing_mode_select_current_option_defaults_when_subentry_removed(
    hass: HomeAssistant,
) -> None:
    """Test current option falls back to default when subentry no longer exists."""
    subentry = _create_subentry(pricing_mode=PRICING_MODE_AEMO)
    entry = _create_entry(hass, subentry)
    coordinator = MagicMock()

    entity = PricingModeSelect(hass, entry, subentry, coordinator)
    entry.subentries = {}

    assert entity.current_option == DEFAULT_PRICING_MODE


async def test_pricing_mode_select_current_option_defaults_when_missing_pricing_mode(
    hass: HomeAssistant,
) -> None:
    """Test current option falls back to default when pricing mode is missing."""
    subentry = _create_subentry(pricing_mode=PRICING_MODE_AEMO)
    subentry.data.pop(CONF_PRICING_MODE)
    entry = _create_entry(hass, subentry)
    coordinator = MagicMock()

    entity = PricingModeSelect(hass, entry, subentry, coordinator)

    assert entity.current_option == DEFAULT_PRICING_MODE


async def test_pricing_mode_select_ignores_invalid_option(hass: HomeAssistant) -> None:
    """Test selecting an invalid option does not update state."""
    subentry = _create_subentry()
    entry = _create_entry(hass, subentry)
    coordinator = MagicMock()
    coordinator.update_pricing_mode = MagicMock()
    coordinator.async_refresh = AsyncMock()
    hass.config_entries.async_update_subentry = MagicMock()

    entity = PricingModeSelect(hass, entry, subentry, coordinator)

    await entity.async_select_option("invalid")

    coordinator.update_pricing_mode.assert_not_called()
    coordinator.async_refresh.assert_not_awaited()
    hass.config_entries.async_update_subentry.assert_not_called()


async def test_pricing_mode_select_device_info(hass: HomeAssistant) -> None:
    """Test pricing mode select exposes expected device metadata."""
    subentry = _create_subentry()
    entry = _create_entry(hass, subentry)
    coordinator = MagicMock()

    entity = PricingModeSelect(hass, entry, subentry, coordinator)

    assert entity.device_info["identifiers"] == {(DOMAIN, "test_site")}
    assert entity.device_info["name"] == "Amber Express - Test Site"
    assert entity.device_info["manufacturer"] == "Amber Electric"
    assert entity.device_info["configuration_url"] == "https://app.amber.com.au"


async def test_async_setup_entry_returns_when_runtime_data_missing(
    hass: HomeAssistant,
) -> None:
    """Test setup returns immediately when runtime data is absent."""
    subentry = _create_subentry()
    entry = _create_entry(hass, subentry)
    entry.runtime_data = None
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_not_called()


async def test_async_setup_entry_skips_site_without_runtime_site_data(
    hass: HomeAssistant,
) -> None:
    """Test setup skips site subentries missing runtime site data."""
    subentry = _create_subentry()
    entry = _create_entry(hass, subentry)
    entry.runtime_data = MagicMock()
    entry.runtime_data.sites = {}
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_not_called()


async def test_async_setup_entry_adds_entities_for_site_subentry(
    hass: HomeAssistant,
) -> None:
    """Test setup adds a pricing mode select for matching site subentries."""
    site_subentry = _create_subentry()
    non_site_subentry = MagicMock()
    non_site_subentry.subentry_type = "other_type"
    non_site_subentry.subentry_id = "other_subentry_id"
    non_site_subentry.data = {CONF_SITE_ID: "other_site"}
    non_site_subentry.title = "Other"
    entry = _create_entry(hass, site_subentry)
    entry.subentries = {
        site_subentry.subentry_id: site_subentry,
        non_site_subentry.subentry_id: non_site_subentry,
    }
    coordinator = MagicMock()
    site_data = MagicMock()
    site_data.coordinator = coordinator
    entry.runtime_data = MagicMock()
    entry.runtime_data.sites = {site_subentry.subentry_id: site_data}
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]
    assert len(entities) == 1
    assert isinstance(entities[0], PricingModeSelect)
    assert async_add_entities.call_args.kwargs["config_subentry_id"] == site_subentry.subentry_id
