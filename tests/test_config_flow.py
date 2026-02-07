"""Tests for config flow."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.api_client import AmberApiError
from custom_components.amber_express.config_flow import validate_api_token
from custom_components.amber_express.const import (
    CONF_API_TOKEN,
    CONF_CONFIRMATION_TIMEOUT,
    CONF_DEMAND_WINDOW_PRICE,
    CONF_ENABLE_WEBSOCKET,
    CONF_FORECAST_INTERVALS,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DEFAULT_FORECAST_INTERVALS,
    DOMAIN,
    SUBENTRY_TYPE_SITE,
)


def _create_mock_site(
    site_id: str,
    nmi: str,
    status: str = "active",
    network: str = "Ausgrid",
) -> MagicMock:
    """Create a mock Site object."""
    mock_site = MagicMock()
    mock_site.id = site_id
    mock_site.nmi = nmi
    mock_site.status = MagicMock(value=status)
    mock_site.network = network
    mock_site.channels = []
    return mock_site


@pytest.fixture
def mock_amber_api_multi_site() -> Generator[MagicMock]:
    """Mock the Amber API client with multiple active sites."""
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_site1 = _create_mock_site("site1", "1111111111", "active", "Ausgrid")
        mock_site2 = _create_mock_site("site2", "2222222222", "active", "Endeavour")

        mock_client.fetch_sites = AsyncMock(return_value=[mock_site1, mock_site2])
        mock_client.last_status = 200

        yield mock_client


@pytest.fixture
def mock_amber_api_inactive_site() -> Generator[MagicMock]:
    """Mock the Amber API client with only inactive sites."""
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_site = _create_mock_site("inactive_site", "9999999999", "closed")
        mock_client.fetch_sites = AsyncMock(return_value=[mock_site])
        mock_client.last_status = 200

        yield mock_client


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


async def test_form_rate_limited(hass: HomeAssistant, mock_amber_api_rate_limited: MagicMock) -> None:
    """Test rate limited error (429)."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_TOKEN: "valid_token"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "rate_limited"}


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
    """Test handling of non-403 API exception (server error)."""
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Server error - raises AmberApiError with status 500
        mock_client.fetch_sites = AsyncMock(side_effect=AmberApiError("Server error", 500))

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


async def test_full_flow_single_site_sets_default_forecast_intervals(
    hass: HomeAssistant, mock_amber_api: MagicMock
) -> None:
    """Test new subentries default forecast interval count is stored."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_TOKEN: "valid_token"})

    with (
        patch("custom_components.amber_express.async_setup_entry", return_value=True),
        patch("custom_components.amber_express.async_unload_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SITE_NAME: "My Home"})

        entry = result["result"]
        subentry = next(iter(entry.subentries.values()))
        assert subentry.data[CONF_FORECAST_INTERVALS] == DEFAULT_FORECAST_INTERVALS

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
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

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

        mock_client.fetch_sites = AsyncMock(return_value=[mock_site])
        mock_client.last_status = 200

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
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

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

        mock_client.fetch_sites = AsyncMock(return_value=[mock_site])
        mock_client.last_status = 200

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


async def test_site_subentry_reconfigure_updates_forecast_intervals(
    hass: HomeAssistant, mock_amber_api: MagicMock
) -> None:
    """Test reconfiguring a site subentry updates forecast interval count."""
    with (
        patch("custom_components.amber_express.async_setup_entry", return_value=True),
        patch("custom_components.amber_express.async_unload_entry", return_value=True),
    ):
        # Create entry with one site subentry via the normal flow
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_TOKEN: "valid_token"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SITE_NAME: "My Home"})

        entry = result["result"]
        subentry = next(iter(entry.subentries.values()))

        # Start a subentry reconfigure flow
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_SITE),
            context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        # Submit existing values, changing only forecast interval count
        user_input = {
            CONF_SITE_NAME: subentry.data[CONF_SITE_NAME],
            CONF_PRICING_MODE: subentry.data[CONF_PRICING_MODE],
            CONF_ENABLE_WEBSOCKET: subentry.data[CONF_ENABLE_WEBSOCKET],
            CONF_WAIT_FOR_CONFIRMED: subentry.data[CONF_WAIT_FOR_CONFIRMED],
            CONF_CONFIRMATION_TIMEOUT: subentry.data[CONF_CONFIRMATION_TIMEOUT],
            CONF_DEMAND_WINDOW_PRICE: subentry.data.get(CONF_DEMAND_WINDOW_PRICE, 0.0),
            CONF_FORECAST_INTERVALS: 576,
        }

        result = await hass.config_entries.subentries.async_configure(result["flow_id"], user_input=user_input)
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"

        updated_subentry = entry.subentries[subentry.subentry_id]
        assert updated_subentry.data[CONF_FORECAST_INTERVALS] == 576

        await hass.config_entries.async_remove(entry.entry_id)


@pytest.mark.parametrize(
    ("forecast_intervals", "expected_error_field"),
    [
        (0, "forecast_intervals"),
        (2049, "forecast_intervals"),
    ],
)
async def test_site_subentry_reconfigure_validates_forecast_intervals(
    hass: HomeAssistant,
    mock_amber_api: MagicMock,
    forecast_intervals: int,
    expected_error_field: str,
) -> None:
    """Test forecast interval count validation in site subentry reconfigure."""
    with (
        patch("custom_components.amber_express.async_setup_entry", return_value=True),
        patch("custom_components.amber_express.async_unload_entry", return_value=True),
    ):
        # Create entry with one site subentry via the normal flow
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_TOKEN: "valid_token"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SITE_NAME: "My Home"})

        entry = result["result"]
        subentry = next(iter(entry.subentries.values()))

        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_SITE),
            context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
        )

        user_input = {
            CONF_SITE_NAME: subentry.data[CONF_SITE_NAME],
            CONF_PRICING_MODE: subentry.data[CONF_PRICING_MODE],
            CONF_ENABLE_WEBSOCKET: subentry.data[CONF_ENABLE_WEBSOCKET],
            CONF_WAIT_FOR_CONFIRMED: subentry.data[CONF_WAIT_FOR_CONFIRMED],
            CONF_CONFIRMATION_TIMEOUT: subentry.data[CONF_CONFIRMATION_TIMEOUT],
            CONF_DEMAND_WINDOW_PRICE: subentry.data.get(CONF_DEMAND_WINDOW_PRICE, 0.0),
            CONF_FORECAST_INTERVALS: forecast_intervals,
        }

        with pytest.raises(InvalidData) as err:
            await hass.config_entries.subentries.async_configure(result["flow_id"], user_input=user_input)

        assert err.value.path == [expected_error_field]
        assert expected_error_field in err.value.schema_errors

        await hass.config_entries.async_remove(entry.entry_id)
