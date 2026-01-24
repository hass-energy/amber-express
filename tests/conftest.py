"""Pytest fixtures for Amber Express tests."""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import amberelectric
from amberelectric.models import CurrentInterval, ForecastInterval
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.const import (
    ATTR_DESCRIPTOR,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_SPOT_PER_KWH,
    ATTR_START_TIME,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_API_TOKEN,
    CONF_ENABLE_CONTROLLED_LOAD,
    CONF_ENABLE_FEED_IN,
    CONF_ENABLE_GENERAL,
    CONF_ENABLE_WEBSOCKET,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DATA_SOURCE_POLLING,
    DEFAULT_ENABLE_CONTROLLED_LOAD,
    DEFAULT_ENABLE_FEED_IN,
    DEFAULT_ENABLE_GENERAL,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_PRICING_MODE,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
)

# Enable loading of the custom component
pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture
def mock_api_token() -> str:
    """Return a mock API token."""
    return "test_api_token_12345"


@pytest.fixture
def mock_site_id() -> str:
    """Return a mock site ID."""
    return "01ABCDEFGHIJKLMNOPQRSTUV"


@pytest.fixture
def mock_site_name() -> str:
    """Return a mock site name."""
    return "Test Site"


@pytest.fixture
def mock_config_entry_data(
    mock_api_token: str,
    mock_site_id: str,
    mock_site_name: str,
) -> dict:
    """Return mock config entry data."""
    return {
        CONF_API_TOKEN: mock_api_token,
        CONF_SITE_ID: mock_site_id,
        CONF_SITE_NAME: mock_site_name,
    }


@pytest.fixture
def mock_config_entry_options() -> dict:
    """Return mock config entry options."""
    return {
        CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
        CONF_ENABLE_GENERAL: DEFAULT_ENABLE_GENERAL,
        CONF_ENABLE_FEED_IN: DEFAULT_ENABLE_FEED_IN,
        CONF_ENABLE_CONTROLLED_LOAD: DEFAULT_ENABLE_CONTROLLED_LOAD,
        CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
        CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
    }


@pytest.fixture
def mock_config_entry(
    mock_config_entry_data: dict,
    mock_config_entry_options: dict,
) -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Site",
        data=mock_config_entry_data,
        options=mock_config_entry_options,
        unique_id=mock_config_entry_data[CONF_SITE_ID],
    )


@pytest.fixture
def mock_amber_api() -> Generator[MagicMock]:
    """Mock the Amber Electric API."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance

        # Mock get_sites response
        mock_site = MagicMock()
        mock_site.id = "01ABCDEFGHIJKLMNOPQRSTUV"
        mock_site.nmi = "1234567890"
        mock_site.status = MagicMock(value="active")
        mock_site.channels = []

        mock_instance.get_sites.return_value = [mock_site]

        yield mock_instance


@pytest.fixture
def mock_amber_api_invalid() -> Generator[MagicMock]:
    """Mock the Amber Electric API with invalid auth."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance

        # Mock get_sites to raise 403
        mock_instance.get_sites.side_effect = amberelectric.ApiException(status=403)

        yield mock_instance


@pytest.fixture
def mock_amber_api_no_sites() -> Generator[MagicMock]:
    """Mock the Amber Electric API with no sites."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance

        # Mock get_sites to return empty list
        mock_instance.get_sites.return_value = []

        yield mock_instance


@pytest.fixture
def mock_amber_api_unknown_error() -> Generator[MagicMock]:
    """Mock the Amber Electric API with unknown error."""
    with patch("custom_components.amber_express.config_flow.amber_api") as mock_api:
        mock_instance = MagicMock()
        mock_api.AmberApi.return_value = mock_instance

        # Mock get_sites to raise generic exception
        mock_instance.get_sites.side_effect = Exception("Unknown error")

        yield mock_instance


@pytest.fixture
def mock_channel_data_general() -> dict:
    """Return mock channel data for general channel."""
    return {
        ATTR_PER_KWH: 0.25,
        ATTR_SPOT_PER_KWH: 0.20,
        ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
        ATTR_END_TIME: "2024-01-01T10:05:00+00:00",
        ATTR_ESTIMATE: False,
        ATTR_DESCRIPTOR: "neutral",
        ATTR_SPIKE_STATUS: "none",
        ATTR_RENEWABLES: 45.5,
        ATTR_FORECASTS: [
            {ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_PER_KWH: 0.26},
            {ATTR_START_TIME: "2024-01-01T10:10:00+00:00", ATTR_PER_KWH: 0.27},
        ],
    }


@pytest.fixture
def mock_channel_data_feed_in() -> dict:
    """Return mock channel data for feed-in channel."""
    return {
        ATTR_PER_KWH: 0.10,
        ATTR_SPOT_PER_KWH: 0.08,
        ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
        ATTR_END_TIME: "2024-01-01T10:05:00+00:00",
        ATTR_ESTIMATE: False,
        ATTR_DESCRIPTOR: "low",
        ATTR_SPIKE_STATUS: "none",
        ATTR_FORECASTS: [
            {ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_PER_KWH: 0.11},
        ],
    }


@pytest.fixture
def mock_coordinator_with_data(
    mock_channel_data_general: dict,
    mock_channel_data_feed_in: dict,
) -> MagicMock:
    """Return a mock coordinator with data."""
    coordinator = MagicMock()
    coordinator.data_source = DATA_SOURCE_POLLING

    # Store data internally for get methods
    data = {
        CHANNEL_GENERAL: mock_channel_data_general,
        CHANNEL_FEED_IN: mock_channel_data_feed_in,
    }
    coordinator.current_data = data

    def get_channel_data(channel: str) -> dict | None:
        return data.get(channel)

    def get_forecasts(channel: str) -> list:
        channel_data = data.get(channel)
        if channel_data:
            return channel_data.get(ATTR_FORECASTS, [])
        return []

    def get_renewables() -> float | None:
        general = data.get(CHANNEL_GENERAL)
        if general:
            return general.get(ATTR_RENEWABLES)
        return None

    def is_price_spike() -> bool:
        general = data.get(CHANNEL_GENERAL)
        if general:
            spike_status = general.get(ATTR_SPIKE_STATUS)
            if spike_status:
                return spike_status.lower() in ("spike", "potential")
        return False

    def is_demand_window() -> bool | None:
        general = data.get(CHANNEL_GENERAL)
        if general:
            return general.get("demand_window")
        return None

    def get_tariff_info() -> dict:
        general = data.get(CHANNEL_GENERAL)
        if not general:
            return {}
        return {
            "period": general.get("tariff_period"),
            "season": general.get("tariff_season"),
            "block": general.get("tariff_block"),
            "demand_window": general.get("demand_window"),
        }

    def get_active_channels() -> list:
        return [ch for ch in [CHANNEL_GENERAL, CHANNEL_FEED_IN, CHANNEL_CONTROLLED_LOAD] if ch in data]

    def get_site_info() -> dict:
        return {
            "id": "01ABCDEFGHIJKLMNOPQRSTUV",
            "nmi": "1234567890",
            "network": "Ausgrid",
            "status": "active",
            "channels": [
                {"type": "general", "tariff": "EA116", "identifier": "E1"},
                {"type": "feedIn", "tariff": "EA029", "identifier": "B1"},
            ],
            "interval_length": 30,
        }

    coordinator.get_channel_data = MagicMock(side_effect=get_channel_data)
    coordinator.get_forecasts = MagicMock(side_effect=get_forecasts)
    coordinator.get_renewables = MagicMock(side_effect=get_renewables)
    coordinator.is_price_spike = MagicMock(side_effect=is_price_spike)
    coordinator.is_demand_window = MagicMock(side_effect=is_demand_window)
    coordinator.get_tariff_info = MagicMock(side_effect=get_tariff_info)
    coordinator.get_active_channels = MagicMock(side_effect=get_active_channels)
    coordinator.get_site_info = MagicMock(side_effect=get_site_info)

    return coordinator


@pytest.fixture
def mock_current_interval() -> CurrentInterval:
    """Return a mock CurrentInterval."""
    interval = MagicMock(spec=CurrentInterval)
    interval.per_kwh = 25.0  # cents
    interval.spot_per_kwh = 20.0
    interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    interval.nem_time = "2024-01-01T10:00:00"
    interval.renewables = 45.5
    interval.estimate = False
    interval.descriptor = MagicMock(value="neutral")
    interval.spike_status = MagicMock(value="none")
    interval.channel_type = MagicMock(value="general")
    interval.advanced_price = None
    interval.tariff_information = None
    return interval


@pytest.fixture
def mock_forecast_interval() -> ForecastInterval:
    """Return a mock ForecastInterval."""
    interval = MagicMock(spec=ForecastInterval)
    interval.per_kwh = 26.0  # cents
    interval.spot_per_kwh = 21.0
    interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    interval.end_time = datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC)
    interval.nem_time = "2024-01-01T10:05:00"
    interval.renewables = 46.0
    interval.descriptor = MagicMock(value="neutral")
    interval.spike_status = MagicMock(value="none")
    interval.channel_type = MagicMock(value="general")
    interval.advanced_price = None
    return interval


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in all tests."""
