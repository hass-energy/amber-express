"""Tests for the data coordinator."""

# pyright: reportArgumentType=false

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from amberelectric.models import CurrentInterval, ForecastInterval
from amberelectric.rest import ApiException
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
from tests.conftest import wrap_interval


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
        return AmberDataCoordinator(hass, mock_config_entry, mock_subentry)

    def test_coordinator_init(self, coordinator: AmberDataCoordinator) -> None:
        """Test coordinator initialization."""
        assert coordinator.api_token == "test_api_token_12345"  # noqa: S105
        assert coordinator.site_id == "01ABCDEFGHIJKLMNOPQRSTUV"
        assert coordinator.data_source == DATA_SOURCE_POLLING
        assert coordinator.current_data == {}

    def test_should_poll_first_run(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll returns True on first run."""
        assert coordinator.current_data == {}
        assert coordinator.should_poll() is True

    def test_should_poll_confirmed_price_stops_polling(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll returns False after confirmed price."""
        coordinator.current_data = {"some": "data"}
        # Trigger interval start and then confirm
        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
            coordinator.should_poll()  # This starts the interval
            coordinator._polling_manager.on_confirmed_received()

            # Now check that polling stops
            result = coordinator.should_poll()
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

    async def test_async_update_data_first_run(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data on first run."""
        with (
            patch.object(coordinator, "_fetch_site_info", new=AsyncMock()) as mock_fetch_site,
            patch.object(coordinator, "_fetch_amber_data", new=AsyncMock()) as mock_fetch_data,
            patch.object(coordinator, "_update_from_sources") as mock_merge,
        ):
            await coordinator._async_update_data()

            mock_fetch_site.assert_called_once()
            mock_fetch_data.assert_called_once()
            mock_merge.assert_called_once()

    async def test_async_update_data_site_info_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data handles site info error."""
        with (
            patch.object(
                coordinator, "_fetch_site_info", new=AsyncMock(side_effect=Exception("Site error"))
            ) as mock_fetch_site,
            patch.object(coordinator, "_fetch_amber_data", new=AsyncMock()),
            patch.object(coordinator, "_update_from_sources"),
        ):
            await coordinator._async_update_data()
            mock_fetch_site.assert_called_once()
            assert coordinator._site_info_fetched is True

    async def test_async_update_data_api_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data raises UpdateFailed on API exception."""
        coordinator._site_info_fetched = True

        with (
            patch.object(coordinator, "_fetch_amber_data", new=AsyncMock(side_effect=ApiException(status=500))),
            pytest.raises(UpdateFailed),
        ):
            await coordinator._async_update_data()

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
        """Test _fetch_site_info when site not found keeps initial info."""
        mock_site = MagicMock()
        mock_site.id = "different_site"

        # Save initial site info from subentry
        initial_site_info = coordinator._site_info.copy()

        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(return_value=[mock_site])):
            await coordinator._fetch_site_info()
            # Site info should be unchanged from subentry data
            assert coordinator._site_info == initial_site_info

    async def test_fetch_site_info_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_site_info handles exception and keeps initial info."""
        # Save initial site info from subentry
        initial_site_info = coordinator._site_info.copy()

        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=Exception("Error"))):
            await coordinator._fetch_site_info()
            # Site info should be unchanged from subentry data
            assert coordinator._site_info == initial_site_info

    async def test_fetch_amber_data_rate_limit_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data respects rate limit backoff."""
        coordinator._rate_limiter.record_rate_limit()  # Sets rate limit

        with patch.object(coordinator.hass, "async_add_executor_job") as mock_job:
            await coordinator._fetch_amber_data()
            mock_job.assert_not_called()

    async def test_fetch_amber_data_429_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles 429 error with backoff."""
        with patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=429))
        ):
            await coordinator._fetch_amber_data()
            assert coordinator._rate_limiter.current_backoff == 10
            assert coordinator._rate_limiter.is_limited() is True

    async def test_fetch_amber_data_429_exponential_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data uses exponential backoff."""
        # First 429 sets backoff to 10
        coordinator._rate_limiter.record_rate_limit()
        assert coordinator._rate_limiter.current_backoff == 10

        # Wait for rate limit to expire by resetting state
        coordinator._rate_limiter._rate_limit_until = None

        with patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=429))
        ):
            await coordinator._fetch_amber_data()
            assert coordinator._rate_limiter.current_backoff == 20

    async def test_fetch_amber_data_other_api_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles other API errors."""
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=ApiException(status=500, reason="Server Error")),
        ):
            await coordinator._fetch_amber_data()

    async def test_fetch_amber_data_generic_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data handles generic exceptions."""
        with patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=Exception("Generic error"))
        ):
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

        wrapped = wrap_interval(mock_interval)
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(return_value=[wrapped])):
            result = await coordinator._fetch_forecasts(30)
            assert result is not None

    async def test_fetch_forecasts_429(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts handles 429 with rate limit and API status tracking."""
        with patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=429))
        ):
            result = await coordinator._fetch_forecasts(30)
            assert result is None
            # Should trigger rate limiter
            assert coordinator._rate_limiter.is_limited() is True
            assert coordinator._rate_limiter.current_backoff == 10
            # Should record API status
            assert coordinator.get_api_status() == 429

    async def test_fetch_forecasts_other_error(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts handles other API errors."""
        with patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=500))
        ):
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

    def test_should_poll_delegates_to_polling_manager(self, coordinator: AmberDataCoordinator) -> None:
        """Test should_poll correctly delegates to SmartPollingManager."""
        # Verify the integration works - detailed behavior tested in test_smart_polling.py
        coordinator.current_data = {"some": "data"}

        with patch("custom_components.amber_express.smart_polling.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

            # First poll should return True (new interval)
            result = coordinator.should_poll()
            assert result is True

            # After confirmed, should return False
            coordinator._polling_manager.on_confirmed_received()
            result = coordinator.should_poll()
            assert result is False

    def test_is_price_spike_null_status(self, coordinator: AmberDataCoordinator) -> None:
        """Test is_price_spike returns False with null spike status."""
        coordinator.current_data = {CHANNEL_GENERAL: {ATTR_SPIKE_STATUS: None}}
        assert coordinator.is_price_spike() is False

    async def test_async_update_data_generic_exception(self, coordinator: AmberDataCoordinator) -> None:
        """Test _async_update_data raises UpdateFailed on generic exception."""
        coordinator._site_info_fetched = True

        with (
            patch.object(coordinator, "_fetch_amber_data", new=AsyncMock(side_effect=Exception("Generic error"))),
            pytest.raises(UpdateFailed),
        ):
            await coordinator._async_update_data()

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

        wrapped = wrap_interval(mock_interval)
        mock_forecast_data = {CHANNEL_GENERAL: {ATTR_PER_KWH: 0.26, ATTR_FORECASTS: []}}

        with (
            patch.object(
                coordinator.hass,
                "async_add_executor_job",
                new=AsyncMock(return_value=[wrapped]),
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

        wrapped = wrap_interval(mock_interval)
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=[wrapped]),
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
        mock_interval.nem_time = None
        mock_interval.renewables = None

        wrapped = wrap_interval(mock_interval)
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=[wrapped]),
        ):
            await coordinator._fetch_amber_data()

            # Should not have updated polling_data (no general channel)
            assert coordinator._data_sources.polling_data == {}

    async def test_fetch_amber_data_success_resets_backoff(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data resets rate limit backoff on success."""
        # Set up a previous rate limit that has now expired
        coordinator._rate_limiter.record_rate_limit()
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
        mock_interval.nem_time = None
        mock_interval.renewables = None

        wrapped = wrap_interval(mock_interval)
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=[wrapped]),
        ):
            await coordinator._fetch_amber_data()

            assert coordinator._rate_limiter.current_backoff == 0
            assert coordinator._rate_limiter.is_limited() is False

    async def test_fetch_amber_data_confirmed_price_forecasts_fail(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test _fetch_amber_data with confirmed price but forecasts fail."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            data={CONF_API_TOKEN: "test"},
            options={},
        )
        entry.add_to_hass(hass)
        subentry = create_mock_subentry_for_coordinator(wait_for_confirmed=True)
        coordinator = AmberDataCoordinator(hass, entry, subentry)

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

        wrapped = wrap_interval(mock_interval)
        with (
            patch.object(
                coordinator.hass,
                "async_add_executor_job",
                new=AsyncMock(return_value=[wrapped]),
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

    async def test_fetch_forecasts_success_sets_status_200(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_forecasts sets status to 200 on success."""
        # Set up a previous error status
        coordinator._set_api_status(429)
        assert coordinator.get_api_status() == 429

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

        wrapped = wrap_interval(mock_interval)
        with patch.object(coordinator.hass, "async_add_executor_job", new=AsyncMock(return_value=[wrapped])):
            result = await coordinator._fetch_forecasts(30)
            assert result is not None
            # API status should be 200
            assert coordinator.get_api_status() == 200

    async def test_fetch_amber_data_records_api_status(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data records API status on failure."""
        with patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=ApiException(status=503))
        ):
            await coordinator._fetch_amber_data()
            assert coordinator.get_api_status() == 503

    async def test_fetch_amber_data_sets_status_200_on_success(self, coordinator: AmberDataCoordinator) -> None:
        """Test _fetch_amber_data sets status to 200 on success."""
        # Set up a previous error status
        coordinator._set_api_status(500)
        assert coordinator.get_api_status() == 500

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

        wrapped = wrap_interval(mock_interval)
        with patch.object(
            coordinator.hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=[wrapped]),
        ):
            await coordinator._fetch_amber_data()
            # API status should be 200
            assert coordinator.get_api_status() == 200

    def test_get_rate_limit_info(self, coordinator: AmberDataCoordinator) -> None:
        """Test get_rate_limit_info returns rate limit details."""
        # Initially no rate limit
        info = coordinator.get_rate_limit_info()
        assert info["rate_limit_until"] is None
        assert info["backoff_seconds"] == 0

        # Record rate limit
        coordinator._rate_limiter.record_rate_limit()
        info = coordinator.get_rate_limit_info()
        assert info["rate_limit_until"] is not None
        assert info["backoff_seconds"] == 10

    def test_api_status_tracking(self, coordinator: AmberDataCoordinator) -> None:
        """Test API status tracking."""
        # Initially 200 (OK)
        assert coordinator.get_api_status() == 200

        # Set error status
        coordinator._set_api_status(429)
        assert coordinator.get_api_status() == 429

        # Set back to 200
        coordinator._set_api_status(200)
        assert coordinator.get_api_status() == 200
