"""Tests for the data coordinator."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from amberelectric.models import CurrentInterval, ForecastInterval, Interval
from amberelectric.rest import ApiException
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DESCRIPTOR,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_SPOT_PER_KWH,
    ATTR_TARIFF_BLOCK,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_API_TOKEN,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DATA_SOURCE_POLLING,
    DATA_SOURCE_WEBSOCKET,
    DOMAIN,
    POLL_MINUTES,
    POLL_SECONDS,
    PRICING_MODE_APP,
)
from custom_components.amber_express.coordinator import CHANNEL_TYPE_MAP, AmberDataCoordinator


class TestSmartPolling:
    """Tests for smart polling logic."""

    def test_poll_seconds_are_valid(self) -> None:
        """Test that poll seconds are within valid range."""
        for second in POLL_SECONDS:
            assert 0 <= second < 60

    def test_poll_minutes_are_valid(self) -> None:
        """Test that poll minutes are within valid range."""
        for minute in POLL_MINUTES:
            assert 0 <= minute < 60

    def test_poll_minutes_cover_interval_starts(self) -> None:
        """Test that poll minutes include the start of each 5-min interval."""
        interval_starts = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
        for start in interval_starts:
            assert start in POLL_MINUTES or start + 1 in POLL_MINUTES


class TestDataMerging:
    """Tests for data merging logic."""

    def test_channel_type_mapping(self) -> None:
        """Test that channel types are mapped correctly."""
        assert "general" in CHANNEL_TYPE_MAP
        assert "feedIn" in CHANNEL_TYPE_MAP
        assert "controlledLoad" in CHANNEL_TYPE_MAP

        assert CHANNEL_TYPE_MAP["general"] == CHANNEL_GENERAL
        assert CHANNEL_TYPE_MAP["feedIn"] == CHANNEL_FEED_IN
        assert CHANNEL_TYPE_MAP["controlledLoad"] == CHANNEL_CONTROLLED_LOAD


class TestAmberDataCoordinator:
    """Tests for AmberDataCoordinator."""

    @pytest.fixture
    def coordinator(self, hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> AmberDataCoordinator:
        """Create a coordinator for testing."""
        mock_config_entry.add_to_hass(hass)
        return AmberDataCoordinator(hass, mock_config_entry)

    def test_coordinator_init(self, coordinator: AmberDataCoordinator) -> None:
        """Test coordinator initialization."""
        assert coordinator.api_token == "test_api_token_12345"
        assert coordinator.site_id == "01ABCDEFGHIJKLMNOPQRSTUV"
        assert coordinator.data_source == DATA_SOURCE_POLLING
        assert coordinator.current_data == {}

    def test_should_poll_first_run(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll returns True on first run."""
        assert coordinator.current_data == {}
        assert coordinator._should_poll_now() is True

    def test_should_poll_confirmed_price_stops_polling(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll returns False after confirmed price."""
        coordinator.current_data = {"some": "data"}
        coordinator._current_interval_start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        coordinator._has_confirmed_price = True
        coordinator._forecasts_pending = False

        with patch("custom_components.amber_express.coordinator.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 30, tzinfo=UTC)
            mock_datetime.min = datetime.min

            result = coordinator._should_poll_now()
            assert result is False

    def test_should_poll_rate_limit(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll respects rate limit."""
        coordinator.current_data = {"some": "data"}
        coordinator._current_interval_start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        coordinator._poll_count_this_interval = 8

        with patch("custom_components.amber_express.coordinator.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 30, tzinfo=UTC)
            mock_datetime.min = datetime.min

            result = coordinator._should_poll_now()
            assert result is False

    def test_should_poll_public_interface(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll public interface."""
        coordinator.current_data = {}
        assert coordinator.should_poll() is True

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
        """Test get_tariff_info."""
        coordinator.current_data = {
            CHANNEL_GENERAL: {
                ATTR_TARIFF_PERIOD: "peak",
                ATTR_TARIFF_SEASON: "summer",
                ATTR_TARIFF_BLOCK: 1,
                ATTR_DEMAND_WINDOW: True,
            }
        }
        result = coordinator.get_tariff_info()
        assert result["period"] == "peak"
        assert result["season"] == "summer"
        assert result["block"] == 1
        assert result["demand_window"] is True

    def test_get_tariff_info_no_data(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_tariff_info with no data."""
        coordinator.current_data = {}
        result = coordinator.get_tariff_info()
        assert result == {}

    def test_get_active_channels(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_active_channels."""
        coordinator.current_data = {CHANNEL_GENERAL: {}, CHANNEL_FEED_IN: {}}
        result = coordinator.get_active_channels()
        assert CHANNEL_GENERAL in result
        assert CHANNEL_FEED_IN in result
        assert CHANNEL_CONTROLLED_LOAD not in result

    def test_get_site_info(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_site_info."""
        coordinator._site_info = {"id": "test", "network": "Ausgrid"}
        result = coordinator.get_site_info()
        assert result == {"id": "test", "network": "Ausgrid"}

    def test_merge_data_polling_only(self, coordinator: AmberDataCoordinator) -> None:
        """Test _merge_data with polling data only."""
        coordinator._polling_data = {CHANNEL_GENERAL: {"price": 0.25}}
        coordinator._polling_timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        coordinator._websocket_data = {}
        coordinator._websocket_timestamp = None

        coordinator._merge_data()

        assert coordinator.current_data[CHANNEL_GENERAL] == {"price": 0.25}
        assert coordinator.data_source == DATA_SOURCE_POLLING

    def test_merge_data_websocket_only(self, coordinator: AmberDataCoordinator) -> None:
        """Test _merge_data with websocket data only."""
        coordinator._polling_data = {}
        coordinator._polling_timestamp = None
        coordinator._websocket_data = {CHANNEL_GENERAL: {"price": 0.30}}
        coordinator._websocket_timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

        coordinator._merge_data()

        assert coordinator.current_data[CHANNEL_GENERAL] == {"price": 0.30}
        assert coordinator.data_source == DATA_SOURCE_WEBSOCKET

    def test_merge_data_websocket_fresher(self, coordinator: AmberDataCoordinator) -> None:
        """Test _merge_data uses fresher websocket data."""
        coordinator._polling_data = {CHANNEL_GENERAL: {"price": 0.25}}
        coordinator._polling_timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        coordinator._websocket_data = {CHANNEL_GENERAL: {"price": 0.30}}
        coordinator._websocket_timestamp = datetime(2024, 1, 1, 10, 0, 30, tzinfo=UTC)

        coordinator._merge_data()

        assert coordinator.current_data[CHANNEL_GENERAL] == {"price": 0.30}
        assert coordinator.data_source == DATA_SOURCE_WEBSOCKET

    def test_merge_data_polling_fresher(self, coordinator: AmberDataCoordinator) -> None:
        """Test _merge_data uses fresher polling data."""
        coordinator._polling_data = {CHANNEL_GENERAL: {"price": 0.25}}
        coordinator._polling_timestamp = datetime(2024, 1, 1, 10, 0, 30, tzinfo=UTC)
        coordinator._websocket_data = {CHANNEL_GENERAL: {"price": 0.30}}
        coordinator._websocket_timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

        coordinator._merge_data()

        assert coordinator.current_data[CHANNEL_GENERAL] == {"price": 0.25}
        assert coordinator.data_source == DATA_SOURCE_POLLING

    def test_merge_data_empty(self, coordinator: AmberDataCoordinator) -> None:
        """Test _merge_data with no data adds metadata."""
        coordinator._polling_data = {}
        coordinator._polling_timestamp = None
        coordinator._websocket_data = {}
        coordinator._websocket_timestamp = None

        coordinator._merge_data()

        # Merge always adds metadata
        assert "_source" in coordinator.current_data
        assert "_polling_timestamp" in coordinator.current_data
        assert "_websocket_timestamp" in coordinator.current_data

    def test_update_from_websocket(self, coordinator: AmberDataCoordinator) -> None:
        """Test update_from_websocket."""
        data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.25}}

        with patch.object(coordinator, "async_set_updated_data") as mock_update:
            coordinator.update_from_websocket(data)

            assert coordinator._websocket_data == data
            assert coordinator._websocket_timestamp is not None
            mock_update.assert_called_once()

    def test_extract_interval_data(self, coordinator: AmberDataCoordinator, mock_current_interval) -> None:
        """Test _extract_interval_data."""
        result = coordinator._extract_interval_data(mock_current_interval)

        assert result[ATTR_PER_KWH] == 0.25
        assert result[ATTR_SPOT_PER_KWH] == 0.20
        assert result[ATTR_ESTIMATE] is False
        assert result[ATTR_DESCRIPTOR] == "neutral"
        assert result[ATTR_SPIKE_STATUS] == "none"

    def test_extract_interval_data_with_advanced_price(self, coordinator: AmberDataCoordinator, mock_current_interval) -> None:
        """Test _extract_interval_data with advanced price."""
        mock_current_interval.advanced_price = MagicMock()
        mock_current_interval.advanced_price.low = 20.0
        mock_current_interval.advanced_price.predicted = 25.0
        mock_current_interval.advanced_price.high = 30.0

        result = coordinator._extract_interval_data(mock_current_interval)

        assert result[ATTR_ADVANCED_PRICE]["low"] == 0.20
        assert result[ATTR_ADVANCED_PRICE]["predicted"] == 0.25
        assert result[ATTR_ADVANCED_PRICE]["high"] == 0.30

    def test_extract_interval_data_with_tariff_info(self, coordinator: AmberDataCoordinator, mock_current_interval) -> None:
        """Test _extract_interval_data with tariff information."""
        mock_current_interval.tariff_information = MagicMock()
        mock_current_interval.tariff_information.demand_window = True
        mock_current_interval.tariff_information.period = "peak"
        mock_current_interval.tariff_information.season = "summer"
        mock_current_interval.tariff_information.block = 1

        result = coordinator._extract_interval_data(mock_current_interval)

        assert result[ATTR_DEMAND_WINDOW] is True
        assert result[ATTR_TARIFF_PERIOD] == "peak"
        assert result[ATTR_TARIFF_SEASON] == "summer"
        assert result[ATTR_TARIFF_BLOCK] == 1

    def test_extract_interval_data_forecast_always_estimated(self, coordinator: AmberDataCoordinator, mock_forecast_interval) -> None:
        """Test _extract_interval_data marks forecasts as estimated."""
        result = coordinator._extract_interval_data(mock_forecast_interval)
        assert result[ATTR_ESTIMATE] is True

    def test_build_forecasts(self, coordinator: AmberDataCoordinator, mock_forecast_interval) -> None:
        """Test _build_forecasts."""
        result = coordinator._build_forecasts([mock_forecast_interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.26

    def test_process_intervals_current_only(self, coordinator: AmberDataCoordinator) -> None:
        """Test _process_intervals with current interval only."""
        interval = MagicMock(spec=CurrentInterval)
        interval.per_kwh = 25.0
        interval.spot_per_kwh = 20.0
        interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.estimate = False
        interval.descriptor = MagicMock(value="neutral")
        interval.spike_status = MagicMock(value="none")
        interval.channel_type = MagicMock(value="general")
        interval.advanced_price = None
        interval.tariff_information = None
        interval.nem_time = None
        interval.renewables = None

        result = coordinator._process_intervals([interval])

        assert CHANNEL_GENERAL in result
        assert result[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25

    def test_process_intervals_with_wrapper(self, coordinator: AmberDataCoordinator) -> None:
        """Test _process_intervals unwraps Interval wrapper."""
        inner_interval = MagicMock(spec=CurrentInterval)
        inner_interval.per_kwh = 25.0
        inner_interval.spot_per_kwh = 20.0
        inner_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        inner_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        inner_interval.estimate = False
        inner_interval.descriptor = MagicMock(value="neutral")
        inner_interval.spike_status = MagicMock(value="none")
        inner_interval.channel_type = MagicMock(value="general")
        inner_interval.advanced_price = None
        inner_interval.tariff_information = None
        inner_interval.nem_time = None
        inner_interval.renewables = None

        wrapper = MagicMock(spec=Interval)
        wrapper.actual_instance = inner_interval

        result = coordinator._process_intervals([wrapper])

        assert CHANNEL_GENERAL in result

    def test_process_intervals_skips_none_wrapper(self, coordinator: AmberDataCoordinator) -> None:
        """Test _process_intervals skips None in wrapper."""
        wrapper = MagicMock(spec=Interval)
        wrapper.actual_instance = None

        result = coordinator._process_intervals([wrapper])

        assert result == {}

    async def test_async_update_data_first_run(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data on first run."""
        with (
            patch.object(coordinator, "_fetch_site_info", new=AsyncMock()) as mock_fetch_site,
            patch.object(coordinator, "_fetch_amber_data", new=AsyncMock()) as mock_fetch_data,
            patch.object(coordinator, "_merge_data") as mock_merge,
        ):
            await coordinator._async_update_data()

            mock_fetch_site.assert_called_once()
            mock_fetch_data.assert_called_once()
            mock_merge.assert_called_once()

    async def test_async_update_data_site_info_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data handles site info error."""
        with (
            patch.object(coordinator, "_fetch_site_info", new=AsyncMock(side_effect=Exception("Site error"))) as mock_fetch_site,
            patch.object(coordinator, "_fetch_amber_data", new=AsyncMock()),
            patch.object(coordinator, "_merge_data"),
        ):
            await coordinator._async_update_data()
            mock_fetch_site.assert_called_once()
            assert coordinator._site_info_fetched is True

    async def test_async_update_data_api_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data raises UpdateFailed on API exception."""
        coordinator._site_info_fetched = True

        with patch.object(coordinator, "_fetch_amber_data", new=AsyncMock(side_effect=ApiException(status=500))):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    async def test_async_update_data_returns_cached_when_no_poll(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data returns cached data when polling not needed."""
        coordinator._site_info_fetched = True
        coordinator.current_data = {"cached": "data"}
        coordinator._has_confirmed_price = True

        with patch.object(coordinator, "_should_poll_now", return_value=False):
            result = await coordinator._async_update_data()
            assert result == {"cached": "data"}

    async def test_fetch_site_info(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_site_info."""
        mock_site = MagicMock()
        mock_site.id = coordinator.site_id
        mock_site.nmi = "1234567890"
        mock_site.network = "Ausgrid"
        mock_site.status = MagicMock(value="active")
        mock_site.active_from = "2024-01-01"
        mock_site.interval_length = 30

        mock_channel = MagicMock()
        mock_channel.type = MagicMock(value="general")
        mock_channel.identifier = "E1"
        mock_channel.tariff = "EA116"
        mock_site.channels = [mock_channel]

        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(return_value=[mock_site])):
            await coordinator._fetch_site_info()

            assert coordinator._site_info["id"] == coordinator.site_id
            assert coordinator._site_info["nmi"] == "1234567890"
            assert coordinator._site_info["network"] == "Ausgrid"
            assert len(coordinator._site_info["channels"]) == 1

    async def test_fetch_site_info_not_found(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_site_info when site not found."""
        mock_site = MagicMock()
        mock_site.id = "different_site"

        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(return_value=[mock_site])):
            await coordinator._fetch_site_info()
            assert coordinator._site_info == {}

    async def test_fetch_site_info_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_site_info handles exception."""
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=Exception("Error"))):
            await coordinator._fetch_site_info()
            assert coordinator._site_info == {}

    async def test_fetch_amber_data_rate_limit_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data respects rate limit backoff."""
        coordinator._rate_limit_until = datetime.now(UTC) + timedelta(seconds=10)

        with patch.object(coordinator.hass, "async_add_executor_job") as mock_job:
            await coordinator._fetch_amber_data()
            mock_job.assert_not_called()

    async def test_fetch_amber_data_429_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles 429 error with backoff."""
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=429))):
            await coordinator._fetch_amber_data()
            assert coordinator._rate_limit_backoff_seconds == 10
            assert coordinator._rate_limit_until is not None

    async def test_fetch_amber_data_429_exponential_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data uses exponential backoff."""
        coordinator._rate_limit_backoff_seconds = 10

        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=429))):
            await coordinator._fetch_amber_data()
            assert coordinator._rate_limit_backoff_seconds == 20

    async def test_fetch_amber_data_other_api_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles other API errors."""
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=500, reason="Server Error"))):
            await coordinator._fetch_amber_data()

    async def test_fetch_amber_data_generic_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles generic exceptions."""
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=Exception("Generic error"))):
            await coordinator._fetch_amber_data()

    async def test_fetch_forecasts_success(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts success."""
        mock_interval = MagicMock(spec=ForecastInterval)
        mock_interval.per_kwh = 26.0
        mock_interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        mock_interval.end_time = datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC)
        mock_interval.channel_type = MagicMock(value="general")
        mock_interval.descriptor = MagicMock(value="neutral")
        mock_interval.spike_status = MagicMock(value="none")
        mock_interval.advanced_price = None
        mock_interval.nem_time = None
        mock_interval.renewables = None

        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(return_value=[mock_interval])):
            result = await coordinator._fetch_forecasts(30)
            assert result is not None

    async def test_fetch_forecasts_429(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts handles 429."""
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=429))):
            result = await coordinator._fetch_forecasts(30)
            assert result is None

    async def test_fetch_forecasts_other_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts handles other API errors."""
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=500))):
            result = await coordinator._fetch_forecasts(30)
            assert result is None

    async def test_fetch_forecasts_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts handles generic exception."""
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=Exception("Error"))):
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

    def test_should_poll_new_interval_resets_state(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll resets state on new interval."""
        coordinator.current_data = {"some": "data"}
        coordinator._current_interval_start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        coordinator._has_confirmed_price = True
        coordinator._forecasts_pending = True
        coordinator._poll_count_this_interval = 5

        with patch("custom_components.amber_express.coordinator.datetime") as mock_datetime:
            # New interval
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 5, 30, tzinfo=UTC)
            mock_datetime.min = datetime.min

            result = coordinator._should_poll_now()

            assert result is True
            assert coordinator._has_confirmed_price is False
            assert coordinator._forecasts_pending is False
            assert coordinator._poll_count_this_interval == 0

    def test_should_poll_forecasts_pending_rate_limited(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll returns False when forecasts pending and rate limited."""
        coordinator.current_data = {"some": "data"}
        coordinator._current_interval_start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        coordinator._has_confirmed_price = True
        coordinator._forecasts_pending = True
        coordinator._rate_limit_until = datetime(2024, 1, 1, 10, 1, 0, tzinfo=UTC)

        with patch("custom_components.amber_express.coordinator.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 30, tzinfo=UTC)
            mock_datetime.min = datetime.min

            result = coordinator._should_poll_now()

            assert result is False

    def test_should_poll_returns_true_normally(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll returns True when no special conditions."""
        coordinator.current_data = {"some": "data"}
        coordinator._current_interval_start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        coordinator._has_confirmed_price = False
        coordinator._forecasts_pending = False
        coordinator._poll_count_this_interval = 1

        with patch("custom_components.amber_express.coordinator.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 30, tzinfo=UTC)
            mock_datetime.min = datetime.min

            result = coordinator._should_poll_now()

            assert result is True

    def test_is_price_spike_null_status(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_price_spike returns False with null spike status."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_SPIKE_STATUS: None}}
        assert coordinator.is_price_spike() is False

    async def test_async_update_data_generic_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data raises UpdateFailed on generic exception."""
        coordinator._site_info_fetched = True

        with patch.object(coordinator, "_fetch_amber_data", new=AsyncMock(side_effect=Exception("Generic error"))):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    def test_process_intervals_missing_channel_type(self, coordinator: AmberDataCoordinator) -> None:
        """Test _process_intervals skips intervals without channel_type attribute."""
        interval = MagicMock()
        # Remove channel_type attribute entirely
        del interval.channel_type

        result = coordinator._process_intervals([interval])
        assert result == {}

    def test_build_forecasts_with_advanced_price(self, coordinator: AmberDataCoordinator) -> None:
        """Test _build_forecasts includes advanced_price when available."""
        interval = MagicMock(spec=ForecastInterval)
        interval.per_kwh = 26.0
        interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.advanced_price = MagicMock()
        interval.advanced_price.predicted = 28.0

        result = coordinator._build_forecasts([interval])

        assert len(result) == 1
        assert ATTR_ADVANCED_PRICE in result[0]
        assert result[0][ATTR_ADVANCED_PRICE] == 0.28

    def test_build_forecasts_app_pricing_mode(self, hass: HomeAssistant) -> None:
        """Test _build_forecasts uses advanced_price in APP pricing mode."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test", CONF_SITE_ID: "test", CONF_SITE_NAME: "Test"},
            options={CONF_PRICING_MODE: PRICING_MODE_APP},
        )
        entry.add_to_hass(hass)
        coordinator = AmberDataCoordinator(hass, entry)

        interval = MagicMock(spec=ForecastInterval)
        interval.per_kwh = 26.0
        interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.advanced_price = MagicMock()
        interval.advanced_price.predicted = 30.0

        result = coordinator._build_forecasts([interval])

        # Should use advanced_price.predicted
        assert result[0][ATTR_PER_KWH] == 0.30

    async def test_fetch_amber_data_retry_forecasts_success(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data retries forecasts and succeeds."""
        coordinator._has_confirmed_price = True
        coordinator._forecasts_pending = True

        mock_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.25, ATTR_FORECASTS: []}}

        with (
            patch.object(coordinator, "_fetch_forecasts", new=AsyncMock(return_value=mock_data)),
            patch.object(coordinator, "_merge_data"),
            patch.object(coordinator, "async_set_updated_data"),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._forecasts_pending is False
            assert coordinator._polling_data == mock_data

    async def test_fetch_amber_data_confirmed_price_with_forecasts(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with confirmed price fetches forecasts."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test", CONF_SITE_ID: "test", CONF_SITE_NAME: "Test"},
            options={CONF_WAIT_FOR_CONFIRMED: True},
        )
        entry.add_to_hass(hass)
        coordinator = AmberDataCoordinator(hass, entry)

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
        mock_interval.nem_time = None
        mock_interval.renewables = None

        mock_forecast_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.26, ATTR_FORECASTS: []}}

        with (
            patch.object(
                coordinator.hass,
                "async_add_executor_job",
                new=AsyncMock(return_value=[mock_interval]),
            ),
            patch.object(coordinator, "_fetch_forecasts", new=AsyncMock(return_value=mock_forecast_data)),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._has_confirmed_price is True
            assert coordinator._forecasts_pending is False

    async def test_fetch_amber_data_estimated_not_wait(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with estimated price when wait_for_confirmed is False."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test", CONF_SITE_ID: "test", CONF_SITE_NAME: "Test"},
            options={CONF_WAIT_FOR_CONFIRMED: False},
        )
        entry.add_to_hass(hass)
        coordinator = AmberDataCoordinator(hass, entry)

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
        mock_interval.nem_time = None
        mock_interval.renewables = None

        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=[mock_interval]),
        ):
            await coordinator._fetch_amber_data()

            # Should update polling data
            assert CHANNEL_GENERAL in coordinator._polling_data

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
        mock_interval.nem_time = None
        mock_interval.renewables = None

        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=[mock_interval]),
        ):
            await coordinator._fetch_amber_data()

            # Should not have updated polling_data (no general channel)
            assert coordinator._polling_data == {}

    async def test_fetch_amber_data_success_resets_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data resets rate limit backoff on success."""
        coordinator._rate_limit_backoff_seconds = 30
        coordinator._rate_limit_until = datetime.now(UTC) - timedelta(seconds=1)

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
        mock_interval.nem_time = None
        mock_interval.renewables = None

        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=[mock_interval]),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._rate_limit_backoff_seconds == 0
            assert coordinator._rate_limit_until is None

    def test_extract_interval_data_app_mode_no_advanced_price(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _extract_interval_data in APP mode falls back to per_kwh."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test", CONF_SITE_ID: "test", CONF_SITE_NAME: "Test"},
            options={CONF_PRICING_MODE: PRICING_MODE_APP},
        )
        entry.add_to_hass(hass)
        coordinator = AmberDataCoordinator(hass, entry)

        interval = MagicMock(spec=CurrentInterval)
        interval.per_kwh = 25.0
        interval.spot_per_kwh = 20.0
        interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.estimate = False
        interval.descriptor = MagicMock(value="neutral")
        interval.spike_status = MagicMock(value="none")
        interval.advanced_price = None  # No advanced price
        interval.tariff_information = None

        result = coordinator._extract_interval_data(interval)

        # Should fall back to per_kwh
        assert result[ATTR_PER_KWH] == 0.25

    def test_extract_interval_data_app_mode_advanced_price_no_predicted(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _extract_interval_data in APP mode with advanced_price but no predicted."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test", CONF_SITE_ID: "test", CONF_SITE_NAME: "Test"},
            options={CONF_PRICING_MODE: PRICING_MODE_APP},
        )
        entry.add_to_hass(hass)
        coordinator = AmberDataCoordinator(hass, entry)

        interval = MagicMock(spec=CurrentInterval)
        interval.per_kwh = 25.0
        interval.spot_per_kwh = 20.0
        interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.estimate = False
        interval.descriptor = MagicMock(value="neutral")
        interval.spike_status = MagicMock(value="none")
        interval.advanced_price = MagicMock()
        interval.advanced_price.predicted = None  # No predicted value
        interval.tariff_information = None

        result = coordinator._extract_interval_data(interval)

        # Should fall back to per_kwh
        assert result[ATTR_PER_KWH] == 0.25

    def test_build_forecasts_app_mode_no_advanced_price(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _build_forecasts in APP mode falls back to per_kwh."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test", CONF_SITE_ID: "test", CONF_SITE_NAME: "Test"},
            options={CONF_PRICING_MODE: PRICING_MODE_APP},
        )
        entry.add_to_hass(hass)
        coordinator = AmberDataCoordinator(hass, entry)

        interval = MagicMock(spec=ForecastInterval)
        interval.per_kwh = 26.0
        interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.advanced_price = None

        result = coordinator._build_forecasts([interval])

        # Should fall back to per_kwh
        assert result[0][ATTR_PER_KWH] == 0.26

    async def test_fetch_amber_data_confirmed_price_forecasts_fail(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with confirmed price but forecasts fail."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test", CONF_SITE_ID: "test", CONF_SITE_NAME: "Test"},
            options={CONF_WAIT_FOR_CONFIRMED: True},
        )
        entry.add_to_hass(hass)
        coordinator = AmberDataCoordinator(hass, entry)

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
        mock_interval.nem_time = None
        mock_interval.renewables = None

        with (
            patch.object(
                coordinator.hass,
                "async_add_executor_job",
                new=AsyncMock(return_value=[mock_interval]),
            ),
            patch.object(coordinator, "_fetch_forecasts", new=AsyncMock(return_value=None)),  # Forecasts fail
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._has_confirmed_price is True
            assert coordinator._forecasts_pending is True  # Should be pending since fetch failed