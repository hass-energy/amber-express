"""Tests for config flow."""

from unittest.mock import MagicMock, patch

import amberelectric
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.config_flow import validate_api_token
from custom_components.amber_express.const import (
    CONF_API_TOKEN,
    CONF_ENABLE_CONTROLLED_LOAD,
    CONF_ENABLE_FEED_IN,
    CONF_ENABLE_GENERAL,
    CONF_ENABLE_WEBSOCKET,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DEFAULT_PRICING_MODE,
    DOMAIN,
)


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


async def test_form_site_selection(hass: HomeAssistant, mock_amber_api: MagicMock) -> None:
    """Test site selection step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "site"


async def test_full_flow(hass: HomeAssistant, mock_amber_api: MagicMock) -> None:
    """Test the full config flow."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    # Step 1: Enter API token
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "site"

    # Step 2: Select site
    # Mock both setup and unload to prevent actual integration loading
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
            {
                CONF_SITE_ID: "01ABCDEFGHIJKLMNOPQRSTUV",
                CONF_SITE_NAME: "My Home",
            },
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "My Home"
        assert result["data"][CONF_API_TOKEN] == "valid_token"
        assert result["data"][CONF_SITE_ID] == "01ABCDEFGHIJKLMNOPQRSTUV"

        # Clean up the entry while mocks are active
        await hass.config_entries.async_remove(result["result"].entry_id)


async def test_full_flow_without_site_name(hass: HomeAssistant, mock_amber_api: MagicMock) -> None:
    """Test the full config flow without providing site name."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

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
            {
                CONF_SITE_ID: "01ABCDEFGHIJKLMNOPQRSTUV",
                # No CONF_SITE_NAME
            },
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        # Should use site_id as title when no name provided
        assert result["title"] == "01ABCDEFGHIJKLMNOPQRSTUV"

        await hass.config_entries.async_remove(result["result"].entry_id)


async def test_already_configured(hass: HomeAssistant, mock_amber_api: MagicMock) -> None:
    """Test that same site cannot be configured twice."""
    # Create an existing entry
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Existing",
        data={CONF_SITE_ID: "01ABCDEFGHIJKLMNOPQRSTUV"},
        unique_id="01ABCDEFGHIJKLMNOPQRSTUV",
    )
    existing_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SITE_ID: "01ABCDEFGHIJKLMNOPQRSTUV",
            CONF_SITE_NAME: "My Home",
        },
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Site",
        data={
            CONF_API_TOKEN: "test_token",
            CONF_SITE_ID: "test_site",
            CONF_SITE_NAME: "Test",
        },
        options={
            CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
            CONF_ENABLE_GENERAL: True,
            CONF_ENABLE_FEED_IN: True,
            CONF_ENABLE_CONTROLLED_LOAD: False,
            CONF_ENABLE_WEBSOCKET: True,
            CONF_WAIT_FOR_CONFIRMED: True,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
            CONF_ENABLE_GENERAL: True,
            CONF_ENABLE_FEED_IN: False,  # Changed
            CONF_ENABLE_CONTROLLED_LOAD: True,  # Changed
            CONF_ENABLE_WEBSOCKET: False,  # Changed
            CONF_WAIT_FOR_CONFIRMED: False,  # Changed
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENABLE_FEED_IN] is False
    assert result["data"][CONF_ENABLE_CONTROLLED_LOAD] is True
    assert result["data"][CONF_ENABLE_WEBSOCKET] is False
    assert result["data"][CONF_WAIT_FOR_CONFIRMED] is False


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
    """Test that site network info is stored in entry data."""
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
                {
                    CONF_SITE_ID: "test_site",
                    CONF_SITE_NAME: "My Home",
                },
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert result["data"]["network"] == "Ausgrid"
            assert result["data"]["nmi"] == "1234567890"
            assert len(result["data"]["channels"]) == 1

            await hass.config_entries.async_remove(result["result"].entry_id)
