"""Tests for config flow."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import amberelectric
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.config_flow import validate_api_token
from custom_components.amber_express.const import (
    CONF_API_TOKEN,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DOMAIN,
    SUBENTRY_TYPE_SITE,
)


@pytest.fixture
def mock_amber_api_multi_site() -> Generator[MagicMock]:
    """Mock the Amber Electric API with multiple active sites."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance

        # Create two mock sites
        mock_site1 = MagicMock()
        mock_site1.id = "site1"
        mock_site1.nmi = "1111111111"
        mock_site1.status = MagicMock(value="active")
        mock_site1.network = "Ausgrid"
        mock_site1.channels = []

        mock_site2 = MagicMock()
        mock_site2.id = "site2"
        mock_site2.nmi = "2222222222"
        mock_site2.status = MagicMock(value="active")
        mock_site2.network = "Endeavour"
        mock_site2.channels = []

        mock_instance.get_sites.return_value = [mock_site1, mock_site2]

        yield mock_instance


@pytest.fixture
def mock_amber_api_inactive_site() -> Generator[MagicMock]:
    """Mock the Amber Electric API with only inactive sites."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance

        mock_site = MagicMock()
        mock_site.id = "inactive_site"
        mock_site.nmi = "9999999999"
        mock_site.status = MagicMock(value="closed")
        mock_site.channels = []

        mock_instance.get_sites.return_value = [mock_site]

        yield mock_instance


async def test_form_user_step(hass: HomeAssistant, mock_amber_api: MagicMock) -> None:
    """Test the user step of the config flow."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_form_invalid_auth(hass: HomeAssistant, mock_amber_api_invalid: MagicMock) -> None:
    """Test invalid auth error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "invalid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_form_no_sites(hass: HomeAssistant, mock_amber_api_no_sites: MagicMock) -> None:
    """Test no sites found error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "no_sites"}


async def test_form_unknown_error(hass: HomeAssistant, mock_amber_api_unknown_error: MagicMock) -> None:
    """Test unknown error handling."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_form_other_api_exception(hass: HomeAssistant) -> None:
    """Test handling of non-403 API exception."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance
        mock_instance.get_sites.side_effect = amberelectric.ApiException(status=500)

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_TOKEN: "valid_token"},
        )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}


async def test_form_single_site_goes_to_name(hass: HomeAssistant, mock_amber_api: MagicMock) -> None:
    """Test that single site goes directly to name_sites step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "name_sites"


async def test_form_multi_site_goes_to_select(hass: HomeAssistant, mock_amber_api_multi_site: MagicMock) -> None:
    """Test that multiple sites go to select_sites step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_sites"


async def test_inactive_sites_filtered(hass: HomeAssistant, mock_amber_api_inactive_site: MagicMock) -> None:
    """Test that inactive sites are filtered out."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    # Should show error since no active sites
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "no_sites"}


async def test_full_flow_single_site(hass: HomeAssistant, mock_amber_api: MagicMock) -> None:
    """Test the full config flow with single site creates entry with subentry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    # Step 1: Enter API token
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "name_sites"

    # Step 2: Enter site name
    with (
        patch(
            "custom_components.amber_express.async_setup_entry",
            return_value=True,
        ),
        patch(
            "custom_components.amber_express.async_unload_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SITE_NAME: "My Home"},
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Amber Electric"
        assert result["data"][CONF_API_TOKEN] == "valid_token"

        # Check that subentries were created
        entry = result["result"]
        assert len(entry.subentries) == 1
        subentry = next(iter(entry.subentries.values()))
        assert subentry.subentry_type == SUBENTRY_TYPE_SITE
        assert subentry.data[CONF_SITE_ID] == "01ABCDEFGHIJKLMNOPQRSTUV"
        assert subentry.data[CONF_SITE_NAME] == "My Home"
        assert subentry.title == "My Home"

        await hass.config_entries.async_remove(entry.entry_id)


async def test_full_flow_multi_site_single_selection(hass: HomeAssistant, mock_amber_api_multi_site: MagicMock) -> None:
    """Test selecting a single site from multiple available sites."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    # Step 1: Enter API token
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_sites"

    # Step 2: Select one site
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"selected_sites": ["site1"]},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "name_sites"

    # Step 3: Enter site name
    with (
        patch(
            "custom_components.amber_express.async_setup_entry",
            return_value=True,
        ),
        patch(
            "custom_components.amber_express.async_unload_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SITE_NAME: "Site One"},
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Amber Electric"

        # Check subentry was created
        entry = result["result"]
        assert len(entry.subentries) == 1
        subentry = next(iter(entry.subentries.values()))
        assert subentry.data[CONF_SITE_ID] == "site1"
        assert subentry.data[CONF_SITE_NAME] == "Site One"
        assert subentry.data["nmi"] == "1111111111"
        assert subentry.data["network"] == "Ausgrid"

        await hass.config_entries.async_remove(entry.entry_id)


async def test_full_flow_multi_site_multiple_selection(
    hass: HomeAssistant, mock_amber_api_multi_site: MagicMock
) -> None:
    """Test selecting multiple sites creates multiple subentries."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    # Step 1: Enter API token
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["step_id"] == "select_sites"

    # Step 2: Select both sites
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"selected_sites": ["site1", "site2"]},
    )

    assert result["step_id"] == "name_sites"

    # Step 3: Name first site
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SITE_NAME: "Home"},
    )

    assert result["step_id"] == "name_sites"

    # Step 4: Name second site
    with (
        patch(
            "custom_components.amber_express.async_setup_entry",
            return_value=True,
        ),
        patch(
            "custom_components.amber_express.async_unload_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SITE_NAME: "Office"},
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY

        # Check both subentries were created
        entry = result["result"]
        assert len(entry.subentries) == 2

        subentries = list(entry.subentries.values())
        site_names = {s.data[CONF_SITE_NAME] for s in subentries}
        assert site_names == {"Home", "Office"}

        await hass.config_entries.async_remove(entry.entry_id)


async def test_already_configured_token(hass: HomeAssistant, mock_amber_api: MagicMock) -> None:
    """Test abort when API token is already configured."""
    # Create an existing entry with the same token
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Amber Electric",
        data={CONF_API_TOKEN: "valid_token"},
        unique_id="amber_existing",
    )
    existing_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_validate_api_token_with_channels(hass: HomeAssistant) -> None:
    """Test validate_api_token extracts channel info."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance

        mock_site = MagicMock()
        mock_site.id = "test_site"
        mock_site.nmi = "1234567890"
        mock_site.status = MagicMock(value="active")
        mock_site.network = "Ausgrid"

        mock_channel = MagicMock()
        mock_channel.type = MagicMock(value="general")
        mock_channel.identifier = "E1"
        mock_channel.tariff = "EA116"
        mock_site.channels = [mock_channel]

        mock_instance.get_sites.return_value = [mock_site]

        result = await validate_api_token(hass, "test_token")

        assert len(result) == 1
        assert result[0]["id"] == "test_site"
        assert result[0]["nmi"] == "1234567890"
        assert result[0]["network"] == "Ausgrid"
        assert len(result[0]["channels"]) == 1
        assert result[0]["channels"][0]["type"] == "general"
        assert result[0]["channels"][0]["tariff"] == "EA116"


async def test_site_with_network_info(hass: HomeAssistant) -> None:
    """Test that site network info is stored in subentry data."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance

        mock_site = MagicMock()
        mock_site.id = "test_site"
        mock_site.nmi = "1234567890"
        mock_site.status = MagicMock(value="active")
        mock_site.network = "Ausgrid"

        mock_channel = MagicMock()
        mock_channel.type = MagicMock(value="general")
        mock_channel.identifier = "E1"
        mock_channel.tariff = "EA116"
        mock_site.channels = [mock_channel]

        mock_instance.get_sites.return_value = [mock_site]

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_TOKEN: "valid_token"},
        )

        # Single site goes directly to name_sites step
        assert result["step_id"] == "name_sites"

        with (
            patch(
                "custom_components.amber_express.async_setup_entry",
                return_value=True,
            ),
            patch(
                "custom_components.amber_express.async_unload_entry",
                return_value=True,
            ),
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_SITE_NAME: "My Home"},
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY

            # Check subentry has network info
            entry = result["result"]
            subentry = next(iter(entry.subentries.values()))
            assert subentry.data["network"] == "Ausgrid"
            assert subentry.data["nmi"] == "1234567890"
            assert len(subentry.data["channels"]) == 1

            await hass.config_entries.async_remove(entry.entry_id)


async def test_no_sites_selected_error(hass: HomeAssistant, mock_amber_api_multi_site: MagicMock) -> None:
    """Test error when no sites are selected."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["step_id"] == "select_sites"

    # Try to submit without selecting any sites
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"selected_sites": []},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "no_sites_selected"}
