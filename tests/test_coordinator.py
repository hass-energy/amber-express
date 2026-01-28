"""Tests for the data coordinator."""

# pyright: reportArgumentType=false

from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from amberelectric.models import CurrentInterval, Interval
from amberelectric.rest import ApiException
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.api_client import AmberApiError
from custom_components.amber_express.const import (
    ATTR_DEMAND_WINDOW,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_TARIFF_BLOCK,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_API_TOKEN,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DATA_SOURCE_POLLING,
    DOMAIN,
)
from custom_components.amber_express.coordinator import AmberDataCoordinator
from custom_components.amber_express.smart_polling import SmartPollingManager
from tests.conftest import make_forecast_interval, make_rate_limit_headers, make_site, wrap_api_response, wrap_interval


def create_mock_subentry_for_coordinator(
    site_id: str = "test",
    *,
    wait_for_confirmed: bool = False,
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
        coord = AmberDataCoordinator(hass, mock_config_entry, mock_subentry)
        # Create polling manager and set site for tests (normally done in start())
        coord._polling_manager = SmartPollingManager(5, 4)
        coord._site = make_site(site_id=coord.site_id, interval_length=5)
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
        """Test _async_update_data fetches data and merges."""
        with (
            patch.object(coordinator, "_fetch_amber_data", new=AsyncMock()) as mock_fetch_data,
            patch.object(coordinator, "_update_from_sources") as mock_merge,
        ):
            await coordinator._async_update_data()

            mock_fetch_data.assert_called_once()
            mock_merge.assert_called_once()

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
        coordinator._rate_limiter.record_rate_limit(60)  # Sets rate limit

        with patch.object(coordinator.hass, "async_add_executor_job") as mock_job:
            await coordinator._fetch_amber_data()
            mock_job.assert_not_called()

    async def test_fetch_amber_data_429_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles 429 error with backoff."""
        err = ApiException(status=429)
        err.headers = make_rate_limit_headers(reset=60)
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=err)):
            await coordinator._fetch_amber_data()
            # 60 + 2 buffer = 62
            assert coordinator._rate_limiter.current_backoff == 62
            assert coordinator._rate_limiter.is_limited() is True

    async def test_fetch_amber_data_429_uses_reset_header(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data uses reset header from 429 response."""
        err = ApiException(status=429)
        err.headers = make_rate_limit_headers(reset=120)
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=err)):
            await coordinator._fetch_amber_data()
            # 120 + 2 buffer = 122
            assert coordinator._rate_limiter.current_backoff == 122

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

    async def test_fetch_forecasts_success(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts success."""
        interval = make_forecast_interval(per_kwh=26.0)
        wrapped = Interval(actual_instance=interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(return_value=mock_response)):
            result = await coordinator._fetch_forecasts(30)
            assert result is not None

    async def test_fetch_forecasts_429(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts handles 429 with rate limit and API status tracking."""
        err = ApiException(status=429)
        err.headers = make_rate_limit_headers(reset=60)
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=err)):
            result = await coordinator._fetch_forecasts(30)
            assert result is None
            # Should trigger rate limiter (60 + 2 buffer = 62)
            assert coordinator._rate_limiter.is_limited() is True
            assert coordinator._rate_limiter.current_backoff == 62
            # Should record API status
            assert coordinator.get_api_status() == 429

    async def test_fetch_forecasts_other_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts handles other API errors."""
        with patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=500))
        ):
            result = await coordinator._fetch_forecasts(30)
            assert result is None

    async def test_fetch_forecasts_api_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts handles API error."""
        with patch.object(
            coordinator._api_client,
            "fetch_current_prices",
            new=AsyncMock(side_effect=AmberApiError("Error", 500)),
        ):
            result = await coordinator._fetch_forecasts(30)
            assert result is None

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

    async def test_fetch_amber_data_retry_forecasts_success(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data retries forecasts and succeeds."""
        coordinator._polling_manager.on_confirmed_received()
        coordinator._polling_manager.set_forecasts_pending()

        mock_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.25, ATTR_FORECASTS: []}}

        with (
            patch.object(coordinator, "_fetch_forecasts", new=AsyncMock(return_value=mock_data)),
            patch.object(coordinator, "_update_from_sources"),
            patch.object(coordinator, "async_set_updated_data"),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._polling_manager.forecasts_pending is False
            assert coordinator._data_sources.polling_data == mock_data

    async def test_fetch_amber_data_confirmed_price_with_forecasts(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with confirmed price fetches forecasts."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True)
        coordinator = AmberDataCoordinator(hass, entry, subentry)
        coordinator._polling_manager = SmartPollingManager(5, 4)
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)

        # Create a confirmed interval (estimate=False)
        mock_interval = MagicMock(spec=CurrentInterval)
        mock_interval.per_kwh = 25.0
        mock_interval.spot_per_kwh = 20.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.estimate = False  # Confirmed!
        mock_interval.descriptor = MagicMock(value="neutral")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.channel_type = MagicMock(value="general")
        mock_interval.advanced_price = None
        mock_interval.tariff_information = None
        mock_interval.nem_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.renewables = 45.0

        wrapped = wrap_interval(mock_interval)
        mock_forecast_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.26, ATTR_FORECASTS: []}}
        mock_response = wrap_api_response([wrapped])

        with (
            patch.object(
                coordinator.hass,
                "async_add_executor_job",
                new=AsyncMock(return_value=mock_response),
            ),
            patch.object(coordinator, "_fetch_forecasts", new=AsyncMock(return_value=mock_forecast_data)),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._polling_manager.has_confirmed_price is True
            assert coordinator._polling_manager.forecasts_pending is False

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
        coordinator = AmberDataCoordinator(hass, entry, subentry)
        coordinator._polling_manager = SmartPollingManager(5, 4)
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)

        mock_interval = MagicMock(spec=CurrentInterval)
        mock_interval.per_kwh = 25.0
        mock_interval.spot_per_kwh = 20.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.estimate = True  # Estimated
        mock_interval.descriptor = MagicMock(value="neutral")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.channel_type = MagicMock(value="general")
        mock_interval.advanced_price = None
        mock_interval.tariff_information = None
        mock_interval.nem_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.renewables = 45.0

        wrapped = wrap_interval(mock_interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Should update polling data
            assert CHANNEL_GENERAL in coordinator._data_sources.polling_data

    async def test_fetch_amber_data_no_general_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data with no general channel data."""
        # Feed-in only interval
        mock_interval = MagicMock(spec=CurrentInterval)
        mock_interval.per_kwh = 10.0
        mock_interval.spot_per_kwh = 8.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.estimate = False
        mock_interval.descriptor = MagicMock(value="low")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.channel_type = MagicMock(value="feedIn")
        mock_interval.advanced_price = None
        mock_interval.tariff_information = None
        mock_interval.nem_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.renewables = 45.0

        wrapped = wrap_interval(mock_interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Should not have updated polling_data (no general channel)
            assert coordinator._data_sources.polling_data == {}

    async def test_fetch_amber_data_success_resets_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data resets rate limit backoff on success."""
        # Set up a previous rate limit that has now expired
        coordinator._rate_limiter.record_rate_limit(60)
        coordinator._rate_limiter._rate_limit_until = datetime.now(UTC) - timedelta(seconds=1)

        mock_interval = MagicMock(spec=CurrentInterval)
        mock_interval.per_kwh = 25.0
        mock_interval.spot_per_kwh = 20.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.estimate = True
        mock_interval.descriptor = MagicMock(value="neutral")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.channel_type = MagicMock(value="general")
        mock_interval.advanced_price = None
        mock_interval.tariff_information = None
        mock_interval.nem_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.renewables = 45.0

        wrapped = wrap_interval(mock_interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._rate_limiter.current_backoff == 0
            assert coordinator._rate_limiter.is_limited() is False

    async def test_fetch_amber_data_confirmed_price_forecasts_fail_subsequent_poll(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with confirmed price on subsequent poll but forecasts fail."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True)
        coordinator = AmberDataCoordinator(hass, entry, subentry)
        coordinator._polling_manager = SmartPollingManager(5, 4)
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)

        # Simulate that first poll already happened (estimate received)
        # This makes the next poll a "subsequent" poll that would need separate forecast fetch
        coordinator._polling_manager._poll_count_this_interval = 1
        coordinator._polling_manager._current_interval_start = datetime.now(UTC)

        # Create a confirmed interval (estimate=False)
        mock_interval = MagicMock(spec=CurrentInterval)
        mock_interval.per_kwh = 25.0
        mock_interval.spot_per_kwh = 20.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.estimate = False  # Confirmed!
        mock_interval.descriptor = MagicMock(value="neutral")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.channel_type = MagicMock(value="general")
        mock_interval.advanced_price = None
        mock_interval.tariff_information = None
        mock_interval.nem_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.renewables = 45.0

        wrapped = wrap_interval(mock_interval)
        mock_response = wrap_api_response([wrapped])
        with (
            patch.object(
                coordinator.hass,
                "async_add_executor_job",
                new=AsyncMock(return_value=mock_response),
            ),
            patch.object(coordinator, "_fetch_forecasts", new=AsyncMock(return_value=None)),  # Forecasts fail
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._polling_manager.has_confirmed_price is True
            assert coordinator._polling_manager.forecasts_pending is True  # Should be pending since fetch failed

    async def test_fetch_forecasts_other_error_records_api_status(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts records API status for non-429 errors."""
        with patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=500))
        ):
            result = await coordinator._fetch_forecasts(30)
            assert result is None
            assert coordinator.get_api_status() == 500
            # Should NOT trigger rate limiter for non-429
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
        coordinator = AmberDataCoordinator(hass, entry, subentry)
        coordinator._polling_manager = SmartPollingManager(5, 4)
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)

        mock_interval = MagicMock(spec=CurrentInterval)
        mock_interval.per_kwh = 25.0
        mock_interval.spot_per_kwh = 20.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.estimate = True
        mock_interval.descriptor = MagicMock(value="neutral")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.channel_type = MagicMock(value="general")
        mock_interval.advanced_price = None
        mock_interval.tariff_information = None
        mock_interval.nem_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.renewables = 45.0

        wrapped = wrap_interval(mock_interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Verify first poll updated data
            assert CHANNEL_GENERAL in coordinator._data_sources.polling_data

    async def test_fetch_amber_data_subsequent_estimate_ignored(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test subsequent estimate polls are ignored (don't update data)."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=False)
        coordinator = AmberDataCoordinator(hass, entry, subentry)
        coordinator._polling_manager = SmartPollingManager(5, 4)
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)

        # Simulate first poll already happened with data
        coordinator._polling_manager._poll_count_this_interval = 1
        coordinator._polling_manager._current_interval_start = datetime.now(UTC)
        initial_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.20, ATTR_FORECASTS: [{"time": "test"}]}}
        coordinator._data_sources.update_polling(initial_data)

        # Create an estimate interval for second poll
        mock_interval = MagicMock(spec=CurrentInterval)
        mock_interval.per_kwh = 30.0  # Different price
        mock_interval.spot_per_kwh = 25.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.estimate = True  # Still estimate
        mock_interval.descriptor = MagicMock(value="neutral")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.channel_type = MagicMock(value="general")
        mock_interval.advanced_price = None
        mock_interval.tariff_information = None
        mock_interval.nem_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.renewables = 45.0

        wrapped = wrap_interval(mock_interval)
        mock_response = wrap_api_response([wrapped])
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await coordinator._fetch_amber_data()

            # Data should NOT be updated - still has original price and forecasts
            assert coordinator._data_sources.polling_data[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.20
            assert coordinator._data_sources.polling_data[CHANNEL_GENERAL][ATTR_FORECASTS] == [{"time": "test"}]

    async def test_fetch_amber_data_first_poll_confirmed_no_separate_forecast_fetch(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test first poll with confirmed price doesn't need separate forecast fetch."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True)
        coordinator = AmberDataCoordinator(hass, entry, subentry)
        coordinator._polling_manager = SmartPollingManager(5, 4)
        coordinator._site = make_site(site_id=coordinator.site_id, interval_length=5)

        # Create a confirmed interval
        mock_interval = MagicMock(spec=CurrentInterval)
        mock_interval.per_kwh = 25.0
        mock_interval.spot_per_kwh = 20.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.estimate = False  # Confirmed!
        mock_interval.descriptor = MagicMock(value="neutral")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.channel_type = MagicMock(value="general")
        mock_interval.advanced_price = None
        mock_interval.tariff_information = None
        mock_interval.nem_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        mock_interval.renewables = 45.0

        wrapped = wrap_interval(mock_interval)
        mock_response = wrap_api_response([wrapped])
        with (
            patch.object(
                coordinator.hass,
                "async_add_executor_job",
                new=AsyncMock(return_value=mock_response),
            ),
            patch.object(coordinator, "_fetch_forecasts", new=AsyncMock()) as mock_fetch_forecasts,
        ):
            await coordinator._fetch_amber_data()

            # _fetch_forecasts should NOT be called on first poll (already has forecasts)
            mock_fetch_forecasts.assert_not_called()
            assert coordinator._polling_manager.has_confirmed_price is True
            # Should NOT have forecasts_pending since first poll already fetched them
            assert coordinator._polling_manager.forecasts_pending is False


class TestCoordinatorLifecycle:
    """Tests for coordinator start/stop lifecycle."""

    @pytest.fixture
    def coordinator(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_subentry: MagicMock
    ) -> AmberDataCoordinator:
        """Create a coordinator for testing."""
        mock_config_entry.add_to_hass(hass)
        coord = AmberDataCoordinator(hass, mock_config_entry, mock_subentry)
        # Create polling manager and set site for tests (normally done in start())
        coord._polling_manager = SmartPollingManager(5, 4)
        coord._site = make_site(site_id=coord.site_id, interval_length=5)
        return coord

    async def test_start_calls_first_refresh(
        self,
        coordinator: AmberDataCoordinator,
        hass: HomeAssistant,  # noqa: ARG002
    ) -> None:
        """Test that start() calls async_config_entry_first_refresh."""
        site = make_site(site_id=coordinator.site_id, interval_length=5)
        coordinator._api_client._rate_limit_info = {"remaining": 45, "limit": 50}

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
        coordinator._api_client._rate_limit_info = {"remaining": 45, "limit": 50}

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

        coordinator._rate_limiter.record_rate_limit(60)
        assert coordinator.is_rate_limited is True

    def test_rate_limit_remaining_seconds(self, coordinator: AmberDataCoordinator) -> None:
        """Test rate_limit_remaining_seconds method."""
        assert coordinator.rate_limit_remaining_seconds() == 0.0

        coordinator._rate_limiter.record_rate_limit(60)
        remaining = coordinator.rate_limit_remaining_seconds()
        assert remaining > 0
        assert remaining <= 62  # 60 + buffer

    def test_get_cdf_polling_stats(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_cdf_polling_stats returns correct stats."""
        stats = coordinator.get_cdf_polling_stats()

        assert stats.observation_count == 100  # Cold start
        assert stats.confirmatory_poll_count == 0
        assert len(stats.scheduled_polls) == 4  # Default k

    def test_get_rate_limit_info(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_rate_limit_info returns api client info."""
        # Initially empty
        info = coordinator.get_rate_limit_info()
        assert info == {}

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
        coordinator._rate_limiter.record_rate_limit(60)

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
        # Set up interval so we have a next poll delay
        with patch("custom_components.amber_express.smart_polling.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            coordinator._polling_manager.should_poll(has_data=True)

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
