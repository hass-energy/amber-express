"""Tests for the data coordinator."""

# pyright: reportArgumentType=false

from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from amberelectric.models.channel_type import ChannelType
from amberelectric.rest import ApiException
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.api_client import AmberApiError
from custom_components.amber_express.cdf_cold_start import get_cold_start_observations
from custom_components.amber_express.cdf_storage import CDFObservationStore
from custom_components.amber_express.const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_SPOT_PER_KWH,
    ATTR_START_TIME,
    ATTR_TARIFF_BLOCK,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_API_TOKEN,
    CONF_CONFIRMATION_TIMEOUT,
    CONF_FORECAST_INTERVALS,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DATA_SOURCE_POLLING,
    DOMAIN,
)
from custom_components.amber_express.coordinator import AmberDataCoordinator
from custom_components.amber_express.smart_polling import SmartPollingManager
from custom_components.amber_express.types import RateLimitInfo
from tests.conftest import make_current_interval, make_rate_limit_headers, make_site, wrap_api_response, wrap_interval


def create_mock_cdf_store() -> MagicMock:
    """Create a mock CDFObservationStore for testing."""
    store = MagicMock(spec=CDFObservationStore)
    store.async_load = AsyncMock(return_value=get_cold_start_observations())
    store.async_save = AsyncMock()
    return store


def create_mock_subentry_for_coordinator(
    site_id: str = "test",
    *,
    wait_for_confirmed: bool = False,
    confirmation_timeout: int = 60,
) -> MagicMock:
    """Create a mock subentry for coordinator tests."""
    subentry = MagicMock()
    subentry.subentry_type = "site"
    subentry.subentry_id = "test_subentry_id"
    subentry.title = "Test"
    subentry.unique_id = site_id
    subentry.data = {
        CONF_SITE_ID: site_id,
        CONF_SITE_NAME: "Test",
        "nmi": "1234567890",
        "network": "Ausgrid",
        "channels": [{"type": "general", "identifier": "E1"}],
        CONF_WAIT_FOR_CONFIRMED: wait_for_confirmed,
        CONF_CONFIRMATION_TIMEOUT: confirmation_timeout,
    }
    return subentry


class TestAmberDataCoordinator:
    """Tests for AmberDataCoordinator."""

    @pytest.fixture
    def coordinator(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_subentry: MagicMock
    ) -> AmberDataCoordinator:
        """Create a coordinator for testing."""
        mock_config_entry.add_to_hass(hass)
        mock_cdf_store = create_mock_cdf_store()
        coord = AmberDataCoordinator(
            hass, mock_config_entry, mock_subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        # Create polling manager and set site for tests (normally done in start())
        coord._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coord._site = make_site(site_id=coord.site_id, interval_length=5)
        coord._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }
        return coord

    def test_coordinator_init(self, coordinator: AmberDataCoordinator) -> None:
        """Test coordinator initialization."""
        assert coordinator.api_token == "test_api_token_12345"  # noqa: S105
        assert coordinator.site_id == "01ABCDEFGHIJKLMNOPQRSTUV"
        assert coordinator.data_source == DATA_SOURCE_POLLING
        assert coordinator.current_data == {}

    def test_get_channel_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_channel_data."""
        coordinator.current_data = {CHANNEL_GENERAL: {"price": 0.25}}
        result = coordinator.get_channel_data(CHANNEL_GENERAL)
        assert result == {"price": 0.25}

    def test_get_channel_data_missing(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_channel_data with missing channel."""
        coordinator.current_data = {}
        result = coordinator.get_channel_data(CHANNEL_GENERAL)
        assert result is None

    def test_get_price(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_price."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.25}}
        result = coordinator.get_price(CHANNEL_GENERAL)
        assert result == 0.25

    def test_get_price_no_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_price with no data."""
        coordinator.current_data = {}
        result = coordinator.get_price(CHANNEL_GENERAL)
        assert result is None

    def test_get_forecasts(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_forecasts."""
        forecasts = [{"start_time": "2024-01-01T10:00:00", "per_kwh": 0.25}]
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_FORECASTS: forecasts}}
        result = coordinator.get_forecasts(CHANNEL_GENERAL)
        assert result == forecasts

    def test_get_forecasts_no_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_forecasts with no data."""
        coordinator.current_data = {}
        result = coordinator.get_forecasts(CHANNEL_GENERAL)
        assert result == []

    def test_get_renewables(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_renewables."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_RENEWABLES: 45.5}}
        result = coordinator.get_renewables()
        assert result == 45.5

    def test_get_renewables_no_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_renewables with no data."""
        coordinator.current_data = {}
        result = coordinator.get_renewables()
        assert result is None

    def test_is_price_spike_true(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_price_spike returns True on spike."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_SPIKE_STATUS: "spike"}}
        assert coordinator.is_price_spike() is True

    def test_is_price_spike_potential(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_price_spike returns True on potential spike."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_SPIKE_STATUS: "potential"}}
        assert coordinator.is_price_spike() is True

    def test_is_price_spike_false(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_price_spike returns False when not spiking."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_SPIKE_STATUS: "none"}}
        assert coordinator.is_price_spike() is False

    def test_is_price_spike_no_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_price_spike returns False with no data."""
        coordinator.current_data = {}
        assert coordinator.is_price_spike() is False

    def test_is_demand_window(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_demand_window."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_DEMAND_WINDOW: True}}
        assert coordinator.is_demand_window() is True

    def test_is_demand_window_no_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_demand_window with no data."""
        coordinator.current_data = {}
        assert coordinator.is_demand_window() is None

    def test_get_tariff_info(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_tariff_info returns TariffInformation."""
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_TARIFF_PERIOD: "peak",
                ATTR_TARIFF_SEASON: "summer",
                ATTR_TARIFF_BLOCK: 1,
                ATTR_DEMAND_WINDOW: True,
            }
        }
        result = coordinator.get_tariff_info()
        assert result is not None
        assert result.period == "peak"
        assert result.season == "summer"
        assert result.block == 1
        assert result.demand_window is True

    def test_get_tariff_info_no_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_tariff_info with no data returns None."""
        coordinator.current_data = {}
        result = coordinator.get_tariff_info()
        assert result is None

    def test_get_active_channels(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_active_channels."""
        coordinator.current_data = {CHANNEL_GENERAL: {}, CHANNEL_FEED_IN: {}}
        result = coordinator.get_active_channels()
        assert CHANNEL_GENERAL in result
        assert CHANNEL_FEED_IN in result
        assert CHANNEL_CONTROLLED_LOAD not in result

    def test_get_site_info(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_site_info returns the Site object."""
        site = make_site(site_id="test", network="Ausgrid")
        coordinator._site = site
        result = coordinator.get_site_info()
        assert result.id == "test"
        assert result.network == "Ausgrid"

    def test_update_from_sources_integration(self, coordinator: AmberDataCoordinator) -> None:
        """Test _update_from_sources correctly integrates with DataSourceMerger."""
        coordinator._data_sources.update_polling({CHANNEL_GENERAL: {"price": 0.25}})

        coordinator._update_from_sources()

        assert coordinator.current_data[CHANNEL_GENERAL] == {"price": 0.25}
        assert coordinator.data_source == DATA_SOURCE_POLLING

    def test_update_from_websocket(self, coordinator: AmberDataCoordinator) -> None:
        """Test update_from_websocket."""
        data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.25}}

        with patch.object(coordinator, "async_set_updated_data") as mock_update:
            coordinator.update_from_websocket(data)

            assert coordinator._data_sources.websocket_data == data
            assert coordinator._data_sources.websocket_timestamp is not None
            mock_update.assert_called_once()

    async def test_async_update_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data calls fetch and returns current_data."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.25}}

        with patch.object(coordinator, "_fetch_amber_data", new=AsyncMock()) as mock_fetch:
            result = await coordinator._async_update_data()

            mock_fetch.assert_called_once()
            assert result == coordinator.current_data

    async def test_fetch_site_info(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_site_info returns the Site object."""
        site = make_site(site_id=coordinator.site_id)

        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=wrap_api_response([site])),
        ):
            result = await coordinator._fetch_site_info()

            assert result.id == coordinator.site_id
            assert result.nmi == "1234567890"
            assert result.network == "Ausgrid"
            assert len(result.channels) == 1

    async def test_fetch_site_info_not_found(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_site_info raises ConfigEntryNotReady when site not found."""
        other_site = make_site(site_id="different_site")

        with (
            patch.object(
                coordinator.hass,
                "async_add_executor_job",
                new=AsyncMock(return_value=wrap_api_response([other_site])),
            ),
            pytest.raises(ConfigEntryNotReady, match="not found"),
        ):
            await coordinator._fetch_site_info()

    async def test_fetch_site_info_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_site_info raises ConfigEntryNotReady on API error."""
        with (
            patch.object(
                coordinator._api_client,
                "fetch_sites",
                new=AsyncMock(side_effect=AmberApiError("Error", 500)),
            ),
            pytest.raises(ConfigEntryNotReady, match="Failed to fetch site info"),
        ):
            await coordinator._fetch_site_info()

    async def test_fetch_site_info_429_raises_config_entry_not_ready(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_site_info raises ConfigEntryNotReady on rate limit."""
        # Create a mock ApiException with headers
        err = ApiException(status=429)
        err.headers = make_rate_limit_headers(reset=120)

        with (
            patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=err)),
            pytest.raises(ConfigEntryNotReady, match="Rate limited"),
        ):
            await coordinator._fetch_site_info()

    async def test_fetch_amber_data_rate_limit_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data respects rate limit backoff."""
        coordinator._rate_limiter.record_rate_limit(None)  # Consume grace
        coordinator._rate_limiter.record_rate_limit(datetime.now(UTC) + timedelta(seconds=60))  # Sets rate limit

        with patch.object(coordinator.hass, "async_add_executor_job") as mock_job:
            await coordinator._fetch_amber_data()
            mock_job.assert_not_called()

    async def test_fetch_amber_data_429_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles 429 error with backoff."""
        coordinator._rate_limiter.record_rate_limit(None)  # Consume grace so mock 429 is second
        err = ApiException(status=429)
        err.headers = make_rate_limit_headers(reset=60)
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=err)):
            await coordinator._fetch_amber_data()
            # 60 + 2 buffer = 62 (may be 61-62 due to timing)
            assert 61 <= coordinator._rate_limiter.current_backoff <= 62
            assert coordinator._rate_limiter.is_limited() is True

    async def test_fetch_amber_data_429_uses_reset_header(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data uses reset header from 429 response."""
        coordinator._rate_limiter.record_rate_limit(None)  # Consume grace so mock 429 is second
        err = ApiException(status=429)
        err.headers = make_rate_limit_headers(reset=120)
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=err)):
            await coordinator._fetch_amber_data()
            # 120 + 2 buffer = 122 (may be 121-122 due to timing)
            assert 121 <= coordinator._rate_limiter.current_backoff <= 122

    async def test_fetch_amber_data_other_api_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles other API errors."""
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=ApiException(status=500, reason="Server Error")),
        ):
            await coordinator._fetch_amber_data()

    async def test_fetch_amber_data_api_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles API errors."""
        with patch.object(
            coordinator._api_client,
            "fetch_current_prices",
            new=AsyncMock(side_effect=AmberApiError("API error", 500)),
        ):
            await coordinator._fetch_amber_data()

    async def test_fetch_amber_data_uses_configured_forecast_intervals(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data uses forecast interval count from subentry config."""
        coordinator.subentry.data = {**coordinator.subentry.data, CONF_FORECAST_INTERVALS: 576}

        intervals = [
            wrap_interval(make_current_interval(channel_type=ChannelType.GENERAL, estimate=False)),
            wrap_interval(make_current_interval(channel_type=ChannelType.FEEDIN, estimate=False)),
        ]
        mock_fetch = AsyncMock(return_value=intervals)

        with patch.object(coordinator._api_client, "fetch_current_prices", new=mock_fetch):
            await coordinator._fetch_amber_data()

        mock_fetch.assert_called_once()
        _args, kwargs = mock_fetch.call_args
        assert kwargs["next_intervals"] == 576

    def test_log_price_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test _log_price_data."""
        data = {
            CHANNEL_GENERAL: {ATTR_PER_KWH: 0.25, ATTR_ESTIMATE: False},
            CHANNEL_FEED_IN: {ATTR_PER_KWH: 0.10, ATTR_ESTIMATE: False},
        }
        coordinator._log_price_data(data, "Test")

    def test_log_price_data_empty(self, coordinator: AmberDataCoordinator) -> None:
        """Test _log_price_data with empty data."""
        coordinator._log_price_data({}, "Test")

    def test_is_price_spike_null_status(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_price_spike returns False with null spike status."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_SPIKE_STATUS: None}}
        assert coordinator.is_price_spike() is False

    async def test_fetch_amber_data_confirmed_price_updates_sensors(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with confirmed price updates sensors and stops polling."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coordinator._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        # Create a confirmed interval (estimate=False) using real SDK object
        interval = make_current_interval(per_kwh=25.0, estimate=False)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])

        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._polling_manager.has_confirmed_price is True
            assert CHANNEL_GENERAL in coordinator._data_sources.polling_data
            # current_data is updated (sensors see the confirmed price)
            assert CHANNEL_GENERAL in coordinator.current_data

    async def test_fetch_amber_data_estimated_not_wait(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with estimated price when wait_for_confirmed is False."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=False)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coordinator._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        interval = make_current_interval(per_kwh=25.0, estimate=True)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Should update polling data and current_data (sensors see the estimate)
            assert CHANNEL_GENERAL in coordinator._data_sources.polling_data
            assert CHANNEL_GENERAL in coordinator.current_data

    async def test_fetch_amber_data_estimated_wait_for_confirmed(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with estimate when wait_for_confirmed is True."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coordinator._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        interval = make_current_interval(per_kwh=25.0, estimate=True)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Data sources ARE updated (latest data is stored)
            assert CHANNEL_GENERAL in coordinator._data_sources.polling_data
            # But current_data is NOT updated (sensors don't see it yet)
            assert coordinator.current_data == {}

    async def test_fetch_amber_data_no_general_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data with no general channel data."""
        # Feed-in only interval
        interval = make_current_interval(per_kwh=10.0, estimate=False, channel_type=ChannelType.FEEDIN)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Should not have updated polling_data (no general channel)
            assert coordinator._data_sources.polling_data == {}

    async def test_fetch_amber_data_success_resets_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data resets rate limit backoff on success."""
        coordinator._rate_limiter.record_rate_limit(None)  # Consume grace
        coordinator._rate_limiter.record_rate_limit(datetime.now(UTC) + timedelta(seconds=60))  # Sets rate limit
        coordinator._rate_limiter._rate_limit_until = datetime.now(UTC) - timedelta(seconds=1)  # Expired

        interval = make_current_interval(per_kwh=25.0, estimate=True)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._rate_limiter.current_backoff == 0
            assert coordinator._rate_limiter.is_limited() is False

    async def test_fetch_amber_data_first_poll_fetches_with_forecasts(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test first poll of interval fetches with forecasts and updates data."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=False)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coordinator._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        interval = make_current_interval(per_kwh=25.0, estimate=True)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Verify first poll updated data
            assert CHANNEL_GENERAL in coordinator._data_sources.polling_data

    async def test_fetch_amber_data_subsequent_estimate_updates_sensors(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test subsequent estimate polls update sensors with new data."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=False)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coordinator._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        # Simulate first poll already happened with data
        coordinator._polling_manager._poll_count_this_interval = 1
        coordinator._polling_manager._current_interval_start = datetime.now(UTC)
        initial_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.20, ATTR_FORECASTS: [{"time": "test"}]}}
        coordinator._data_sources.update_polling(initial_data)

        # Create an estimate interval for second poll with different price
        interval = make_current_interval(per_kwh=30.0, estimate=True)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Data SHOULD be updated - new price from subsequent poll
            assert coordinator._data_sources.polling_data[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.30


class TestCoordinatorLifecycle:
    """Tests for coordinator start/stop lifecycle."""

    @pytest.fixture
    def coordinator(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_subentry: MagicMock
    ) -> AmberDataCoordinator:
        """Create a coordinator for testing."""
        mock_config_entry.add_to_hass(hass)
        mock_cdf_store = create_mock_cdf_store()
        coord = AmberDataCoordinator(
            hass, mock_config_entry, mock_subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        # Create polling manager and set site for tests (normally done in start())
        coord._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coord._site = make_site(site_id=coord.site_id, interval_length=5)
        coord._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }
        return coord

    async def test_start_calls_first_refresh(
        self,
        coordinator: AmberDataCoordinator,
        hass: HomeAssistant,  # noqa: ARG002
    ) -> None:
        """Test that start() calls async_config_entry_first_refresh."""
        site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        with (
            patch.object(coordinator, "_fetch_site_info", new=AsyncMock(return_value=site)) as mock_fetch_site,
            patch.object(coordinator, "async_config_entry_first_refresh", new=AsyncMock()) as mock_refresh,
            patch("custom_components.amber_express.coordinator.async_track_time_change") as mock_track,
        ):
            mock_track.return_value = MagicMock()  # Return unsub function

            await coordinator.start()

            mock_fetch_site.assert_called_once()
            mock_refresh.assert_called_once()
            mock_track.assert_called_once()

    async def test_start_sets_up_time_change_listener(
        self,
        coordinator: AmberDataCoordinator,
        hass: HomeAssistant,  # noqa: ARG002
    ) -> None:
        """Test that start() sets up interval detection."""
        mock_unsub = MagicMock()
        site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        with (
            patch.object(coordinator, "_fetch_site_info", new=AsyncMock(return_value=site)),
            patch.object(coordinator, "async_config_entry_first_refresh", new=AsyncMock()),
            patch(
                "custom_components.amber_express.coordinator.async_track_time_change",
                return_value=mock_unsub,
            ),
        ):
            await coordinator.start()

            assert coordinator._unsub_time_change is mock_unsub

    async def test_stop_unsubscribes_time_change(
        self,
        coordinator: AmberDataCoordinator,
        hass: HomeAssistant,  # noqa: ARG002
    ) -> None:
        """Test that stop() unsubscribes from time change listener."""
        mock_unsub = MagicMock()
        coordinator._unsub_time_change = mock_unsub

        await coordinator.stop()

        mock_unsub.assert_called_once()
        assert coordinator._unsub_time_change is None

    async def test_stop_cancels_pending_poll(
        self,
        coordinator: AmberDataCoordinator,
        hass: HomeAssistant,  # noqa: ARG002
    ) -> None:
        """Test that stop() cancels pending scheduled poll."""
        mock_cancel = MagicMock()
        coordinator._cancel_next_poll = mock_cancel

        await coordinator.stop()

        mock_cancel.assert_called_once()
        assert coordinator._cancel_next_poll is None

    async def test_stop_handles_no_listeners(
        self,
        coordinator: AmberDataCoordinator,
        hass: HomeAssistant,  # noqa: ARG002
    ) -> None:
        """Test that stop() handles case where listeners are already None."""
        coordinator._unsub_time_change = None
        coordinator._cancel_next_poll = None

        # Should not raise
        await coordinator.stop()

    def test_has_confirmed_price_property(self, coordinator: AmberDataCoordinator) -> None:
        """Test has_confirmed_price property."""
        assert coordinator.has_confirmed_price is False

        coordinator._polling_manager.on_confirmed_received()
        assert coordinator.has_confirmed_price is True

    def test_is_rate_limited_property(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_rate_limited property."""
        assert coordinator.is_rate_limited is False

        coordinator._rate_limiter.record_rate_limit(None)  # Consume grace
        coordinator._rate_limiter.record_rate_limit(datetime.now(UTC) + timedelta(seconds=60))
        assert coordinator.is_rate_limited is True

    def test_rate_limit_remaining_seconds(self, coordinator: AmberDataCoordinator) -> None:
        """Test rate_limit_remaining_seconds method."""
        assert coordinator.rate_limit_remaining_seconds() == 0.0

        coordinator._rate_limiter.record_rate_limit(None)  # Consume grace
        coordinator._rate_limiter.record_rate_limit(datetime.now(UTC) + timedelta(seconds=60))
        remaining = coordinator.rate_limit_remaining_seconds()
        assert remaining > 0
        assert remaining <= 62  # 60 + buffer

    def test_get_cdf_polling_stats(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_cdf_polling_stats returns correct stats."""
        # remaining=9 gives 4 polls after buffer of 5
        rate_limit_info: RateLimitInfo = {
            "limit": 50,
            "remaining": 9,
            "reset_seconds": 300,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            coordinator._polling_manager.should_poll(has_data=True)
            coordinator._polling_manager.update_budget(rate_limit_info)

        stats = coordinator.get_cdf_polling_stats()

        assert stats.observation_count == 100  # Cold start
        assert stats.confirmatory_poll_count == 0
        # k=4 total: 3 CDF polls + 1 forced poll at interval end = 4 total
        assert len(stats.scheduled_polls) == 4
        assert stats.scheduled_polls[-1] == 300.0  # Forced poll at interval end

    def test_get_rate_limit_info(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_rate_limit_info returns api client info."""
        info = coordinator.get_rate_limit_info()
        assert info["remaining"] == 45
        assert info["limit"] == 50
        assert info["window_seconds"] == 300
        assert info["policy"] == "50;w=300"
        assert "reset_at" in info

    def test_cancel_pending_poll(self, coordinator: AmberDataCoordinator) -> None:
        """Test _cancel_pending_poll cancels and clears callback."""
        mock_cancel = MagicMock()
        coordinator._cancel_next_poll = mock_cancel

        coordinator._cancel_pending_poll()

        mock_cancel.assert_called_once()
        assert coordinator._cancel_next_poll is None

    def test_cancel_pending_poll_when_none(self, coordinator: AmberDataCoordinator) -> None:
        """Test _cancel_pending_poll handles None gracefully."""
        coordinator._cancel_next_poll = None

        # Should not raise
        coordinator._cancel_pending_poll()

    async def test_do_scheduled_poll_skips_when_confirmed(self, coordinator: AmberDataCoordinator) -> None:
        """Test _do_scheduled_poll skips when confirmed price exists."""
        coordinator._polling_manager._has_confirmed_price = True

        with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
            await coordinator._do_scheduled_poll()

            mock_refresh.assert_not_called()

    async def test_do_scheduled_poll_refreshes_when_not_confirmed(self, coordinator: AmberDataCoordinator) -> None:
        """Test _do_scheduled_poll refreshes when no confirmed price."""
        coordinator._polling_manager._has_confirmed_price = False

        with (
            patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh,
            patch.object(coordinator, "_schedule_next_poll") as mock_schedule,
        ):
            await coordinator._do_scheduled_poll()

            mock_refresh.assert_called_once()
            mock_schedule.assert_called_once()

    def test_schedule_next_poll_skips_when_confirmed(self, coordinator: AmberDataCoordinator) -> None:
        """Test _schedule_next_poll does nothing when confirmed."""
        coordinator._polling_manager._has_confirmed_price = True

        with patch("custom_components.amber_express.coordinator.async_call_later") as mock_call_later:
            coordinator._schedule_next_poll()

            mock_call_later.assert_not_called()

    def test_schedule_next_poll_schedules_rate_limit_resume(self, coordinator: AmberDataCoordinator) -> None:
        """Test _schedule_next_poll schedules resume when rate limited."""
        coordinator._rate_limiter.record_rate_limit(None)  # Consume grace
        coordinator._rate_limiter.record_rate_limit(datetime.now(UTC) + timedelta(seconds=60))

        with patch("custom_components.amber_express.coordinator.async_call_later") as mock_call_later:
            mock_call_later.return_value = MagicMock()

            coordinator._schedule_next_poll()

            mock_call_later.assert_called_once()
            # First arg to async_call_later is hass, second is delay
            args = mock_call_later.call_args
            delay = args[0][1]
            assert delay > 60  # At least 60 + 1 second buffer

    def test_schedule_next_poll_schedules_next(self, coordinator: AmberDataCoordinator) -> None:
        """Test _schedule_next_poll schedules when polls remain."""
        # remaining=10 gives 5 polls after buffer of 5
        rate_limit_info: RateLimitInfo = {
            "limit": 50,
            "remaining": 10,
            "reset_seconds": 300,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        # Set up interval so we have a next poll delay
        with patch("custom_components.amber_express.smart_polling.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            coordinator._polling_manager.should_poll(has_data=True)
            coordinator._polling_manager.update_budget(rate_limit_info)

        with patch("custom_components.amber_express.coordinator.async_call_later") as mock_call_later:
            mock_call_later.return_value = MagicMock()

            coordinator._schedule_next_poll()

            mock_call_later.assert_called_once()

    async def test_on_interval_check_new_interval(self, coordinator: AmberDataCoordinator) -> None:
        """Test _on_interval_check triggers refresh on new interval."""
        with (
            patch.object(coordinator._polling_manager, "check_new_interval", return_value=True),
            patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh,
            patch.object(coordinator, "_schedule_next_poll") as mock_schedule,
            patch.object(coordinator, "_cancel_pending_poll") as mock_cancel,
        ):
            await coordinator._on_interval_check(None)

            mock_cancel.assert_called_once()
            mock_refresh.assert_called_once()
            mock_schedule.assert_called_once()

    async def test_on_interval_check_same_interval(self, coordinator: AmberDataCoordinator) -> None:
        """Test _on_interval_check does nothing for same interval."""
        with (
            patch.object(coordinator._polling_manager, "check_new_interval", return_value=False),
            patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh,
        ):
            await coordinator._on_interval_check(None)

            mock_refresh.assert_not_called()

    async def test_on_scheduled_poll_creates_task(self, coordinator: AmberDataCoordinator, hass: HomeAssistant) -> None:
        """Test _on_scheduled_poll creates async task."""
        # Capture the coroutine that gets passed to async_create_task
        created_coro: Coroutine[Any, Any, None] | None = None

        def capture_task(coro: Coroutine[Any, Any, None]) -> MagicMock:
            nonlocal created_coro
            created_coro = coro
            return MagicMock()

        with patch.object(hass, "async_create_task", side_effect=capture_task):
            coordinator._on_scheduled_poll(datetime.now(UTC))

            # Await the captured coroutine to prevent warning
            if created_coro is not None:
                # Mock the internals to prevent actual API calls
                with (
                    patch.object(coordinator, "async_refresh", new=AsyncMock()),
                    patch.object(coordinator, "_schedule_next_poll"),
                ):
                    await created_coro


class TestConfirmationTimeout:
    """Tests for confirmation timeout behavior."""

    @pytest.fixture
    def coordinator_with_timeout(self, hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> AmberDataCoordinator:
        """Create a coordinator with wait_for_confirmed=True and timeout=60."""
        mock_config_entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True, confirmation_timeout=60)
        mock_cdf_store = create_mock_cdf_store()
        coord = AmberDataCoordinator(
            hass, mock_config_entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coord._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coord._site = make_site(site_id=coord.site_id, interval_length=5)
        coord._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }
        return coord

    def test_schedule_confirmation_timeout_schedules_timer(
        self, coordinator_with_timeout: AmberDataCoordinator
    ) -> None:
        """Test _schedule_confirmation_timeout schedules a timer."""
        with patch("custom_components.amber_express.coordinator.async_call_later") as mock_call_later:
            mock_call_later.return_value = MagicMock()

            coordinator_with_timeout._schedule_confirmation_timeout()

            mock_call_later.assert_called_once()
            args = mock_call_later.call_args
            delay = args[0][1]
            assert delay == 60

    def test_schedule_confirmation_timeout_resets_flag(self, coordinator_with_timeout: AmberDataCoordinator) -> None:
        """Test _schedule_confirmation_timeout resets the expired flag."""
        coordinator_with_timeout._confirmation_timeout_expired = True

        with patch("custom_components.amber_express.coordinator.async_call_later") as mock_call_later:
            mock_call_later.return_value = MagicMock()

            coordinator_with_timeout._schedule_confirmation_timeout()

            assert coordinator_with_timeout._confirmation_timeout_expired is False

    def test_schedule_confirmation_timeout_skips_when_not_waiting(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test _schedule_confirmation_timeout does nothing when wait_for_confirmed=False."""
        mock_config_entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=False)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, mock_config_entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )

        with patch("custom_components.amber_express.coordinator.async_call_later") as mock_call_later:
            coordinator._schedule_confirmation_timeout()

            mock_call_later.assert_not_called()

    def test_schedule_confirmation_timeout_skips_when_timeout_zero(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test _schedule_confirmation_timeout does nothing when timeout=0."""
        mock_config_entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True, confirmation_timeout=0)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, mock_config_entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )

        with patch("custom_components.amber_express.coordinator.async_call_later") as mock_call_later:
            coordinator._schedule_confirmation_timeout()

            mock_call_later.assert_not_called()

    def test_on_confirmation_timeout_sets_flag_and_updates(
        self, coordinator_with_timeout: AmberDataCoordinator
    ) -> None:
        """Test _on_confirmation_timeout sets flag and updates sensors."""
        # Put some data in the data sources
        coordinator_with_timeout._data_sources.update_polling({CHANNEL_GENERAL: {ATTR_PER_KWH: 0.25}})

        with patch.object(coordinator_with_timeout, "async_set_updated_data") as mock_update:
            coordinator_with_timeout._on_confirmation_timeout(datetime.now(UTC))

            assert coordinator_with_timeout._confirmation_timeout_expired is True
            assert CHANNEL_GENERAL in coordinator_with_timeout.current_data
            mock_update.assert_called_once()

    def test_cancel_pending_confirmation_timeout(self, coordinator_with_timeout: AmberDataCoordinator) -> None:
        """Test _cancel_pending_confirmation_timeout cancels and clears callback."""
        mock_cancel = MagicMock()
        coordinator_with_timeout._cancel_confirmation_timeout = mock_cancel

        coordinator_with_timeout._cancel_pending_confirmation_timeout()

        mock_cancel.assert_called_once()
        assert coordinator_with_timeout._cancel_confirmation_timeout is None

    def test_cancel_pending_confirmation_timeout_when_none(
        self, coordinator_with_timeout: AmberDataCoordinator
    ) -> None:
        """Test _cancel_pending_confirmation_timeout handles None gracefully."""
        coordinator_with_timeout._cancel_confirmation_timeout = None

        # Should not raise
        coordinator_with_timeout._cancel_pending_confirmation_timeout()

    async def test_fetch_amber_data_estimate_updates_after_timeout(self, hass: HomeAssistant) -> None:
        """Test estimates update sensors after timeout expires."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True, confirmation_timeout=60)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coordinator._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        # Simulate timeout has expired
        coordinator._confirmation_timeout_expired = True

        interval = make_current_interval(per_kwh=25.0, estimate=True)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Data should be in both polling data and current_data
            assert CHANNEL_GENERAL in coordinator._data_sources.polling_data
            assert CHANNEL_GENERAL in coordinator.current_data

    async def test_fetch_amber_data_confirmed_cancels_timeout(self, hass: HomeAssistant) -> None:
        """Test confirmed price cancels the timeout timer."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True, confirmation_timeout=60)
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coordinator._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }

        # Set up a pending timeout
        mock_cancel = MagicMock()
        coordinator._cancel_confirmation_timeout = mock_cancel

        interval = make_current_interval(per_kwh=25.0, estimate=False)
        wrapped = wrap_interval(interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator._api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            mock_cancel.assert_called_once()
            assert coordinator._cancel_confirmation_timeout is None

    async def test_on_interval_check_schedules_timeout(self, coordinator_with_timeout: AmberDataCoordinator) -> None:
        """Test _on_interval_check schedules confirmation timeout on new interval."""
        with (
            patch.object(coordinator_with_timeout._polling_manager, "check_new_interval", return_value=True),
            patch.object(coordinator_with_timeout, "async_refresh", new=AsyncMock()),
            patch.object(coordinator_with_timeout, "_schedule_next_poll"),
            patch.object(coordinator_with_timeout, "_schedule_confirmation_timeout") as mock_schedule_timeout,
        ):
            await coordinator_with_timeout._on_interval_check(None)

            mock_schedule_timeout.assert_called_once()

    async def test_stop_cancels_confirmation_timeout(self, coordinator_with_timeout: AmberDataCoordinator) -> None:
        """Test stop() cancels pending confirmation timeout."""
        mock_cancel = MagicMock()
        coordinator_with_timeout._cancel_confirmation_timeout = mock_cancel

        await coordinator_with_timeout.stop()

        mock_cancel.assert_called_once()
        assert coordinator_with_timeout._cancel_confirmation_timeout is None


class TestHeldPriceAtBoundary:
    """Tests for held price push at interval boundary."""

    def _coordinator_with_held_config(
        self,
        hass: HomeAssistant,
        *,
        wait_for_confirmed: bool = True,
        confirmation_timeout: int = 60,
    ) -> AmberDataCoordinator:
        """Create coordinator with optional wait_for_confirmed and timeout."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(
            wait_for_confirmed=wait_for_confirmed,
            confirmation_timeout=confirmation_timeout,
        )
        mock_cdf_store = create_mock_cdf_store()
        coordinator = AmberDataCoordinator(
            hass, entry, subentry, cdf_store=mock_cdf_store, observations=get_cold_start_observations()
        )
        coordinator._polling_manager = SmartPollingManager(5, get_cold_start_observations())
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {
            "remaining": 45,
            "limit": 50,
            "reset_at": datetime.now(UTC) + timedelta(seconds=300),
            "window_seconds": 300,
            "policy": "50;w=300",
        }
        return coordinator

    def test_held_price_pushed_when_wait_for_confirmed(self, hass: HomeAssistant) -> None:
        """Test held price is pushed at boundary when wait_for_confirmed is True."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_SPOT_PER_KWH: 0.20,
                ATTR_ESTIMATE: False,
                ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
                ATTR_END_TIME: "2024-01-01T10:05:00+00:00",
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25, "estimate": False},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30, "estimate": True},
                    {"start_time": "2024-01-01T10:10:00+00:00", "per_kwh": 0.28, "estimate": True},
                ],
            },
            "_source": DATA_SOURCE_POLLING,
        }

        with patch.object(coordinator, "async_set_updated_data") as mock_update:
            coordinator._push_held_price_at_boundary()

            mock_update.assert_called_once()
        general = coordinator.current_data.get(CHANNEL_GENERAL)
        assert general is not None
        assert general[ATTR_PER_KWH] == 0.25
        assert general[ATTR_ESTIMATE] is True
        forecasts = general[ATTR_FORECASTS]
        assert len(forecasts) == 2
        assert forecasts[0]["start_time"] == "2024-01-01T10:05:00+00:00"
        assert forecasts[0][ATTR_PER_KWH] == 0.25
        assert forecasts[1]["start_time"] == "2024-01-01T10:10:00+00:00"

    def test_held_price_not_pushed_when_not_waiting(self, hass: HomeAssistant) -> None:
        """Test held price is NOT pushed when wait_for_confirmed is False."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=False)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30},
                ],
            },
        }

        with patch.object(coordinator, "async_set_updated_data") as mock_update:
            coordinator._push_held_price_at_boundary()

            mock_update.assert_not_called()

    def test_held_price_not_pushed_when_current_data_empty(self, hass: HomeAssistant) -> None:
        """Test held price is NOT pushed when current_data is empty."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {}

        with patch.object(coordinator, "async_set_updated_data") as mock_update:
            coordinator._push_held_price_at_boundary()

            mock_update.assert_not_called()

    def test_held_price_not_pushed_when_fewer_than_two_forecasts(self, hass: HomeAssistant) -> None:
        """Test held price is NOT pushed when forecast list has fewer than 2 entries."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                ],
            },
        }

        with patch.object(coordinator, "async_set_updated_data") as mock_update:
            coordinator._push_held_price_at_boundary()

            mock_update.assert_not_called()

    def test_held_price_shifts_forecasts_forward(self, hass: HomeAssistant) -> None:
        """Test held price correctly shifts forecasts forward and holds all previous attrs."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_RENEWABLES: 50.0,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30, ATTR_RENEWABLES: 80.0},
                    {"start_time": "2024-01-01T10:10:00+00:00", "per_kwh": 0.28},
                ],
            },
        }

        coordinator._push_held_price_at_boundary()

        general = coordinator.current_data[CHANNEL_GENERAL]
        assert general[ATTR_START_TIME] == "2024-01-01T10:05:00+00:00"
        assert general[ATTR_PER_KWH] == 0.25
        assert general.get(ATTR_RENEWABLES) == 50.0
        assert general[ATTR_FORECASTS][0]["start_time"] == "2024-01-01T10:05:00+00:00"
        assert general[ATTR_FORECASTS][1]["start_time"] == "2024-01-01T10:10:00+00:00"

    def test_held_price_preserves_all_price_fields(self, hass: HomeAssistant) -> None:
        """Test held price preserves per_kwh, spot_per_kwh, advanced_price_predicted."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        advanced = {"low": 0.20, "predicted": 0.25, "high": 0.30}
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_SPOT_PER_KWH: 0.22,
                ATTR_ADVANCED_PRICE: advanced,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30, "spot_per_kwh": 0.28},
                ],
            },
        }

        coordinator._push_held_price_at_boundary()

        general = coordinator.current_data[CHANNEL_GENERAL]
        assert general[ATTR_PER_KWH] == 0.25
        assert general[ATTR_SPOT_PER_KWH] == 0.22
        assert general[ATTR_ADVANCED_PRICE] == advanced

    def test_held_price_sets_estimate_true(self, hass: HomeAssistant) -> None:
        """Test held price sets estimate=True on the new current interval."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25, "estimate": False},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30, "estimate": True},
                ],
            },
        }

        coordinator._push_held_price_at_boundary()

        assert coordinator.current_data[CHANNEL_GENERAL][ATTR_ESTIMATE] is True

    def test_held_price_multiple_channels(self, hass: HomeAssistant) -> None:
        """Test held price works with general and feed_in channels."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30},
                ],
            },
            CHANNEL_FEED_IN: {
                ATTR_PER_KWH: 0.10,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.10},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.08},
                ],
            },
        }

        coordinator._push_held_price_at_boundary()

        assert coordinator.current_data[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25
        assert coordinator.current_data[CHANNEL_FEED_IN][ATTR_PER_KWH] == 0.10
        assert coordinator.current_data[CHANNEL_GENERAL][ATTR_FORECASTS][0]["start_time"] == "2024-01-01T10:05:00+00:00"
        assert coordinator.current_data[CHANNEL_FEED_IN][ATTR_FORECASTS][0]["start_time"] == "2024-01-01T10:05:00+00:00"

    def test_held_price_overwritten_when_confirmed_arrives(self, hass: HomeAssistant) -> None:
        """Test held price is overwritten when confirmed price is received."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: True,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:10:00+00:00", "per_kwh": 0.28},
                ],
            },
        }
        coordinator._data_sources.update_polling(
            {
                CHANNEL_GENERAL: {
                    ATTR_PER_KWH: 0.27,
                    ATTR_ESTIMATE: False,
                    ATTR_FORECASTS: [
                        {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.27},
                        {"start_time": "2024-01-01T10:10:00+00:00", "per_kwh": 0.28},
                    ],
                },
            }
        )

        coordinator._update_from_sources()

        assert coordinator.current_data[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.27
        assert coordinator.current_data[CHANNEL_GENERAL][ATTR_ESTIMATE] is False

    def test_held_price_overwritten_when_timeout_fires(self, hass: HomeAssistant) -> None:
        """Test held price is overwritten when confirmation timeout expires."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: True,
                ATTR_FORECASTS: [{"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.25}],
            },
        }
        coordinator._data_sources.update_polling(
            {
                CHANNEL_GENERAL: {
                    ATTR_PER_KWH: 0.30,
                    ATTR_ESTIMATE: True,
                    ATTR_FORECASTS: [{"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30}],
                },
            }
        )

        coordinator._confirmation_timeout_expired = True
        coordinator._on_confirmation_timeout(datetime.now(UTC))

        assert coordinator.current_data[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.30
        assert coordinator.current_data[CHANNEL_GENERAL][ATTR_ESTIMATE] is True

    async def test_on_interval_check_calls_held_price_before_refresh(self, hass: HomeAssistant) -> None:
        """Test _on_interval_check calls _push_held_price_at_boundary (pre-boundary) before async_refresh."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30},
                ],
            },
        }
        call_order: list[str] = []

        async def record_refresh() -> None:
            call_order.append("refresh")

        with (
            patch.object(coordinator, "_seconds_until_next_boundary", return_value=1.0),
            patch.object(coordinator._polling_manager, "check_new_interval", return_value=True),
            patch.object(coordinator, "_push_held_price_at_boundary") as mock_held,
            patch.object(coordinator, "async_refresh", new=AsyncMock(side_effect=record_refresh)),
            patch.object(coordinator, "_schedule_next_poll"),
            patch.object(coordinator, "_cancel_pending_poll"),
            patch.object(coordinator, "_schedule_confirmation_timeout"),
        ):
            mock_held.return_value = True
            mock_held.side_effect = lambda: call_order.append("held") or True

            await coordinator._on_interval_check(None)

            assert call_order == ["held", "refresh"]

    async def test_pre_boundary_push_fires_when_within_lead_window(self, hass: HomeAssistant) -> None:
        """Test held price is pushed in pre-boundary window when seconds until boundary <= lead."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30},
                ],
            },
        }
        with (
            patch.object(coordinator, "_seconds_until_next_boundary", return_value=0.5),
            patch.object(coordinator._polling_manager, "check_new_interval", return_value=False),
            patch.object(coordinator, "_push_held_price_at_boundary") as mock_held,
        ):
            mock_held.return_value = True

            await coordinator._on_interval_check(None)

            mock_held.assert_called_once()
            assert coordinator._held_price_pushed is True

    async def test_pre_boundary_push_does_not_fire_when_outside_lead_window(self, hass: HomeAssistant) -> None:
        """Test held price is not pushed when seconds until boundary > lead."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30},
                ],
            },
        }
        with (
            patch.object(coordinator, "_seconds_until_next_boundary", return_value=10.0),
            patch.object(coordinator._polling_manager, "check_new_interval", return_value=False),
            patch.object(coordinator, "_push_held_price_at_boundary") as mock_held,
        ):
            await coordinator._on_interval_check(None)

            mock_held.assert_not_called()

    async def test_flag_prevents_double_push_when_pre_boundary_and_boundary_same_tick(
        self, hass: HomeAssistant
    ) -> None:
        """Test _push_held_price_at_boundary only called once when pre-boundary then boundary in same tick."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30},
                ],
            },
        }
        with (
            patch.object(coordinator, "_seconds_until_next_boundary", return_value=1.0),
            patch.object(coordinator._polling_manager, "check_new_interval", return_value=True),
            patch.object(coordinator, "_push_held_price_at_boundary") as mock_held,
            patch.object(coordinator, "async_refresh", new=AsyncMock()),
            patch.object(coordinator, "_schedule_next_poll"),
            patch.object(coordinator, "_cancel_pending_poll"),
            patch.object(coordinator, "_schedule_confirmation_timeout"),
        ):
            mock_held.return_value = True

            await coordinator._on_interval_check(None)

            mock_held.assert_called_once()
            assert coordinator._held_price_pushed is False

    def test_held_price_forward_projects_demand_window_starting(self, hass: HomeAssistant) -> None:
        """Test held price picks up demand_window=True from the next interval."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30, ATTR_DEMAND_WINDOW: True},
                    {"start_time": "2024-01-01T10:10:00+00:00", "per_kwh": 0.28},
                ],
            },
        }

        coordinator._push_held_price_at_boundary()

        general = coordinator.current_data[CHANNEL_GENERAL]
        assert general[ATTR_DEMAND_WINDOW] is True

    def test_held_price_forward_projects_demand_window_ending(self, hass: HomeAssistant) -> None:
        """Test held price clears demand_window when next interval has it False."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_DEMAND_WINDOW: True,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25, ATTR_DEMAND_WINDOW: True},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30, ATTR_DEMAND_WINDOW: False},
                    {"start_time": "2024-01-01T10:10:00+00:00", "per_kwh": 0.28},
                ],
            },
        }

        coordinator._push_held_price_at_boundary()

        general = coordinator.current_data[CHANNEL_GENERAL]
        assert general[ATTR_DEMAND_WINDOW] is False

    def test_held_price_removes_demand_window_when_absent_from_next(self, hass: HomeAssistant) -> None:
        """Test held price removes demand_window when next interval has no tariff info."""
        coordinator = self._coordinator_with_held_config(hass, wait_for_confirmed=True)
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_PER_KWH: 0.25,
                ATTR_DEMAND_WINDOW: True,
                ATTR_ESTIMATE: False,
                ATTR_FORECASTS: [
                    {"start_time": "2024-01-01T10:00:00+00:00", "per_kwh": 0.25, ATTR_DEMAND_WINDOW: True},
                    {"start_time": "2024-01-01T10:05:00+00:00", "per_kwh": 0.30},
                    {"start_time": "2024-01-01T10:10:00+00:00", "per_kwh": 0.28},
                ],
            },
        }

        coordinator._push_held_price_at_boundary()

        general = coordinator.current_data[CHANNEL_GENERAL]
        assert ATTR_DEMAND_WINDOW not in general
