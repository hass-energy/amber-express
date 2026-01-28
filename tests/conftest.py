"""Pytest fixtures for Amber Express tests."""

from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from amberelectric.models import CurrentInterval, ForecastInterval, Interval, Site
from amberelectric.models.advanced_price import AdvancedPrice
from amberelectric.models.channel import Channel
from amberelectric.models.channel_type import ChannelType
from amberelectric.models.price_descriptor import PriceDescriptor
from amberelectric.models.site_status import SiteStatus
from amberelectric.models.spike_status import SpikeStatus
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.api_client import AmberApiError, RateLimitedError
from custom_components.amber_express.cdf_polling import CDFPollingStats
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
    CONF_ENABLE_WEBSOCKET,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DATA_SOURCE_POLLING,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_PRICING_MODE,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
    SUBENTRY_TYPE_SITE,
)

# Enable loading of the custom component
pytest_plugins = "pytest_homeassistant_custom_component"


def make_rate_limit_headers(
    *,
    limit: int = 50,
    remaining: int = 45,
    reset: int = 180,
    window: int = 300,
) -> dict[str, str]:
    """Create valid rate limit headers for testing."""
    return {
        "ratelimit-limit": str(limit),
        "ratelimit-remaining": str(remaining),
        "ratelimit-reset": str(reset),
        "ratelimit-policy": f"{limit};w={window}",
    }


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
def mock_config_entry_data(mock_api_token: str) -> dict:
    """Return mock config entry data (main entry only has API token)."""
    return {
        CONF_API_TOKEN: mock_api_token,
    }


@pytest.fixture
def mock_subentry_data(
    mock_site_id: str,
    mock_site_name: str,
) -> dict:
    """Return mock subentry data for a site."""
    return {
        CONF_SITE_ID: mock_site_id,
        CONF_SITE_NAME: mock_site_name,
        "nmi": "1234567890",
        "network": "Ausgrid",
        "channels": [
            {"type": "general", "tariff": "EA116", "identifier": "E1"},
            {"type": "feedIn", "tariff": "EA029", "identifier": "B1"},
        ],
        CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
        CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
        CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
    }


@pytest.fixture
def mock_subentry(
    mock_site_id: str,
    mock_site_name: str,
) -> MagicMock:
    """Return a mock subentry."""
    subentry = MagicMock()
    subentry.subentry_type = SUBENTRY_TYPE_SITE
    subentry.subentry_id = "test_subentry_id"
    subentry.title = mock_site_name
    subentry.unique_id = mock_site_id
    subentry.data = {
        CONF_SITE_ID: mock_site_id,
        CONF_SITE_NAME: mock_site_name,
        "nmi": "1234567890",
        "network": "Ausgrid",
        "channels": [
            {"type": "general", "tariff": "EA116", "identifier": "E1"},
            {"type": "feedIn", "tariff": "EA029", "identifier": "B1"},
        ],
        CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
        CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
        CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
    }
    return subentry


@pytest.fixture
def mock_config_entry(
    mock_config_entry_data: dict,
    mock_subentry: MagicMock,
) -> MockConfigEntry:
    """Return a mock config entry with a site subentry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Amber Electric",
        data=mock_config_entry_data,
        options={},
        unique_id=f"amber_{hash(mock_config_entry_data[CONF_API_TOKEN])}",
    )
    # Mock subentries property for tests
    entry.subentries = {"test_subentry_id": mock_subentry}
    return entry


def _create_mock_site(
    site_id: str = "01ABCDEFGHIJKLMNOPQRSTUV",
    nmi: str = "1234567890",
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
def mock_amber_api() -> Generator[MagicMock]:
    """Mock the Amber API client for config flow."""
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock successful fetch_sites
        mock_site = _create_mock_site()
        mock_client.fetch_sites = AsyncMock(return_value=[mock_site])
        mock_client.last_status = 200

        yield mock_client


@pytest.fixture
def mock_amber_api_invalid() -> Generator[MagicMock]:
    """Mock the Amber API client with invalid auth (403)."""
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock 403 error - raises AmberApiError with status 403
        mock_client.fetch_sites = AsyncMock(side_effect=AmberApiError("Forbidden", 403))

        yield mock_client


@pytest.fixture
def mock_amber_api_no_sites() -> Generator[MagicMock]:
    """Mock the Amber API client with no sites."""
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock empty sites list
        mock_client.fetch_sites = AsyncMock(return_value=[])
        mock_client.last_status = 200

        yield mock_client


@pytest.fixture
def mock_amber_api_rate_limited() -> Generator[MagicMock]:
    """Mock the Amber API client with rate limiting (429)."""
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock 429 error - raises RateLimitedError
        mock_client.fetch_sites = AsyncMock(side_effect=RateLimitedError(60))

        yield mock_client


@pytest.fixture
def mock_amber_api_unknown_error() -> Generator[MagicMock]:
    """Mock the Amber API client with unknown error."""
    with patch("custom_components.amber_express.config_flow.AmberApiClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock server error - raises AmberApiError with status 500
        mock_client.fetch_sites = AsyncMock(side_effect=AmberApiError("Server error", 500))

        yield mock_client


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
            {ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_PER_KWH: 0.26, "advanced_price_predicted": 0.28},
            {ATTR_START_TIME: "2024-01-01T10:10:00+00:00", ATTR_PER_KWH: 0.27, "advanced_price_predicted": 0.29},
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
            {ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_PER_KWH: 0.11, "advanced_price_predicted": 0.12},
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

    def get_site_info() -> Site:
        return Site(
            id="01ABCDEFGHIJKLMNOPQRSTUV",
            nmi="1234567890",
            network="Ausgrid",
            status=SiteStatus.ACTIVE,
            channels=[
                Channel(identifier="E1", type=ChannelType.GENERAL, tariff="EA116"),
                Channel(identifier="B1", type=ChannelType.FEEDIN, tariff="EA029"),
            ],
            interval_length=30,
        )

    def get_cdf_polling_stats() -> CDFPollingStats:
        return CDFPollingStats(
            observation_count=100,
            scheduled_polls=[21.0, 27.0, 33.0, 39.0],
            next_poll_index=0,
            confirmatory_poll_count=0,
            polls_per_interval=4,
            last_observation=None,
        )

    def get_api_status() -> int:
        return 200

    def get_rate_limit_info() -> dict:
        return {
            "limit": 50,
            "remaining": 45,
            "reset_seconds": 300,
            "window_seconds": 300,
            "policy": "50;w=300",
        }

    coordinator.get_channel_data = MagicMock(side_effect=get_channel_data)
    coordinator.get_forecasts = MagicMock(side_effect=get_forecasts)
    coordinator.get_renewables = MagicMock(side_effect=get_renewables)
    coordinator.is_price_spike = MagicMock(side_effect=is_price_spike)
    coordinator.is_demand_window = MagicMock(side_effect=is_demand_window)
    coordinator.get_tariff_info = MagicMock(side_effect=get_tariff_info)
    coordinator.get_active_channels = MagicMock(side_effect=get_active_channels)
    coordinator.get_site_info = MagicMock(side_effect=get_site_info)
    coordinator.get_cdf_polling_stats = MagicMock(side_effect=get_cdf_polling_stats)
    coordinator.get_api_status = MagicMock(side_effect=get_api_status)
    coordinator.get_rate_limit_info = MagicMock(side_effect=get_rate_limit_info)

    return coordinator


def wrap_interval(inner: MagicMock) -> MagicMock:
    """Wrap an interval in an Interval wrapper for testing."""
    wrapper = MagicMock(spec=Interval)
    wrapper.actual_instance = inner
    return wrapper


class MockApiResponse:
    """Mock ApiResponse for testing get_current_prices_with_http_info."""

    def __init__(
        self,
        data: list,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize mock API response."""
        self.data = data
        self.headers = headers or {
            "ratelimit-policy": "50;w=300",
            "ratelimit-limit": "50",
            "ratelimit-remaining": "49",
            "ratelimit-reset": "300",
        }


def wrap_api_response(
    intervals: list,
    headers: dict[str, str] | None = None,
) -> MockApiResponse:
    """Wrap intervals in a mock ApiResponse for testing."""
    return MockApiResponse(intervals, headers)


# =============================================================================
# Real SDK Object Factories
# =============================================================================


def make_site(
    *,
    site_id: str = "01ABCDEFGHIJKLMNOPQRSTUV",
    nmi: str = "1234567890",
    network: str = "Ausgrid",
    status: SiteStatus = SiteStatus.ACTIVE,
    interval_length: float = 30,
    channels: list[Channel] | None = None,
    active_from: date | None = None,
) -> Site:
    """Create a real Site object for testing."""
    if channels is None:
        channels = [Channel(identifier="E1", type=ChannelType.GENERAL, tariff="EA116")]
    return Site(
        id=site_id,
        nmi=nmi,
        network=network,
        status=status,
        interval_length=interval_length,
        channels=channels,
        active_from=active_from,
    )


def make_current_interval(
    *,
    per_kwh: float = 25.0,
    spot_per_kwh: float = 20.0,
    renewables: float = 45.0,
    estimate: bool = False,
    channel_type: ChannelType = ChannelType.GENERAL,
    descriptor: PriceDescriptor = PriceDescriptor.NEUTRAL,
    spike_status: SpikeStatus = SpikeStatus.NONE,
    start_time: datetime | None = None,
    advanced_price: AdvancedPrice | None = None,
) -> CurrentInterval:
    """Create a real CurrentInterval object for testing."""
    start = start_time or datetime(2024, 1, 1, 9, 30, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    return CurrentInterval(
        type="CurrentInterval",
        duration=30,
        spot_per_kwh=spot_per_kwh,
        per_kwh=per_kwh,
        var_date=date(2024, 1, 1),
        nem_time=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
        start_time=start,
        end_time=end,
        renewables=renewables,
        channel_type=channel_type,
        spike_status=spike_status,
        descriptor=descriptor,
        estimate=estimate,
        advanced_price=advanced_price,
    )


def make_forecast_interval(
    *,
    per_kwh: float = 26.0,
    spot_per_kwh: float = 20.0,
    renewables: float = 45.0,
    channel_type: ChannelType = ChannelType.GENERAL,
    descriptor: PriceDescriptor = PriceDescriptor.NEUTRAL,
    spike_status: SpikeStatus = SpikeStatus.NONE,
    start_time: datetime | None = None,
    advanced_price: AdvancedPrice | None = None,
) -> ForecastInterval:
    """Create a real ForecastInterval object for testing."""
    start = start_time or datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    return ForecastInterval(
        type="ForecastInterval",
        duration=30,
        spot_per_kwh=spot_per_kwh,
        per_kwh=per_kwh,
        var_date=date(2024, 1, 1),
        nem_time=datetime(2024, 1, 1, 10, 30, 0, tzinfo=UTC),
        start_time=start,
        end_time=end,
        renewables=renewables,
        channel_type=channel_type,
        spike_status=spike_status,
        descriptor=descriptor,
        advanced_price=advanced_price,
    )


@pytest.fixture
def mock_current_interval() -> MagicMock:
    """Return a mock CurrentInterval (unwrapped, for direct use)."""
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
def mock_current_interval_wrapped(mock_current_interval: MagicMock) -> MagicMock:
    """Return a mock CurrentInterval wrapped in Interval."""
    return wrap_interval(mock_current_interval)


@pytest.fixture
def mock_forecast_interval() -> MagicMock:
    """Return a mock ForecastInterval (unwrapped, for direct use)."""
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


@pytest.fixture
def mock_forecast_interval_wrapped(mock_forecast_interval: MagicMock) -> MagicMock:
    """Return a mock ForecastInterval wrapped in Interval."""
    return wrap_interval(mock_forecast_interval)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in all tests."""
