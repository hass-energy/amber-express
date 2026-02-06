"""Tests for sensor platform."""

# pyright: reportArgumentType=false

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from amberelectric.models import Site
from amberelectric.models.channel import Channel
from amberelectric.models.channel_type import ChannelType
from amberelectric.models.site_status import SiteStatus
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData
from custom_components.amber_express.const import (
    ATTR_ADVANCED_PRICE,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_START_TIME,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from custom_components.amber_express.sensor import (
    CHANNEL_PRICE_DETAILED_TRANSLATION_KEY,
    CHANNEL_PRICE_TRANSLATION_KEY,
    FORECAST_SOURCE_AEMO,
    FORECAST_SOURCE_AMBER_HIGH,
    FORECAST_SOURCE_AMBER_LOW,
    FORECAST_SOURCE_AMBER_PREDICTED,
    AmberApiStatusSensor,
    AmberConfirmationLagSensor,
    AmberDetailedPriceSensor,
    AmberForecastPriceSensor,
    AmberNextPollSensor,
    AmberPollingStatsSensor,
    AmberPriceSensor,
    AmberRateLimitRemainingSensor,
    AmberRateLimitResetSensor,
    AmberRenewablesSensor,
    AmberSiteSensor,
    async_setup_entry,
)


def create_mock_subentry(
    site_id: str = "test_site_id",
    site_name: str = "Test",
    pricing_mode: str = "app",
) -> MagicMock:
    """Create a mock subentry."""
    subentry = MagicMock()
    subentry.subentry_type = SUBENTRY_TYPE_SITE
    subentry.subentry_id = "test_subentry_id"
    subentry.title = site_name
    subentry.unique_id = site_id
    subentry.data = {
        CONF_SITE_ID: site_id,
        CONF_SITE_NAME: site_name,
        "nmi": "1234567890",
        "network": "Ausgrid",
        "channels": [{"type": "general", "tariff": "EA116", "identifier": "E1"}],
        CONF_PRICING_MODE: pricing_mode,
    }
    return subentry


class TestAmberPriceSensor:
    """Tests for AmberPriceSensor."""

    def test_price_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price sensor initialization."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_{CHANNEL_GENERAL}_price"
        assert sensor._attr_translation_key == "general_price"
        assert sensor._attr_native_unit_of_measurement == "$/kWh"

    def test_price_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price sensor returns correct value."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value == 0.25

    def test_price_sensor_feed_in_negated(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test feed-in price is negated."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_FEED_IN,
        )

        # Feed-in price is negated (earnings shown as negative cost)
        assert sensor.native_value == -0.10

    def test_price_sensor_no_data(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price sensor with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_price_sensor_null_price(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price sensor with null price in data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value={ATTR_PER_KWH: None})
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_price_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price sensor extra attributes."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        attrs = sensor.extra_state_attributes
        # Times are converted to local timezone and rounded to the minute
        expected_start = (
            dt_util.as_local(dt_util.parse_datetime("2024-01-01T10:00:00+00:00"))
            .replace(second=0, microsecond=0)
            .isoformat()
        )
        expected_end = (
            dt_util.as_local(dt_util.parse_datetime("2024-01-01T10:05:00+00:00"))
            .replace(second=0, microsecond=0)
            .isoformat()
        )
        assert attrs[ATTR_START_TIME] == expected_start
        assert attrs[ATTR_END_TIME] == expected_end
        assert attrs[ATTR_ESTIMATE] is False
        assert attrs["data_source"] == "polling"

    def test_price_sensor_extra_attributes_no_data(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price sensor extra attributes with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.extra_state_attributes == {}

    def test_price_sensor_uses_pricing_mode_aemo(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor uses per_kwh when pricing mode is AEMO."""
        subentry = create_mock_subentry(pricing_mode="aemo")

        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        # AEMO pricing mode uses per_kwh
        assert sensor.native_value == 0.25

    def test_price_sensor_uses_pricing_mode_app(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor uses advanced_price_predicted when pricing mode is APP."""
        subentry = create_mock_subentry(pricing_mode=PRICING_MODE_APP)

        # Add advanced price to mock data
        mock_coordinator_with_data.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: 0.25,
                ATTR_ADVANCED_PRICE: 0.28,
                ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
            }
        )

        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        # APP pricing mode uses advanced_price_predicted
        assert sensor.native_value == 0.28

    def test_price_sensor_app_mode_fallback_to_per_kwh(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor falls back to per_kwh when advanced price not available."""
        subentry = create_mock_subentry(pricing_mode=PRICING_MODE_APP)

        # No advanced price in mock data
        mock_coordinator_with_data.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: 0.25,
                ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
            }
        )

        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        # Should fall back to per_kwh
        assert sensor.native_value == 0.25

    def test_price_sensor_includes_forecast_attribute(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price sensor includes forecast in attributes."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        attrs = sensor.extra_state_attributes
        assert "forecast" in attrs
        assert len(attrs["forecast"]) == 2

        # Check time/value format (default is APP mode, uses advanced_price_predicted)
        # Times are converted to local timezone and rounded to the minute
        first_forecast = attrs["forecast"][0]
        assert "time" in first_forecast
        assert "value" in first_forecast
        expected_time = (
            dt_util.as_local(dt_util.parse_datetime("2024-01-01T10:05:00+00:00"))
            .replace(second=0, microsecond=0)
            .isoformat()
        )
        assert first_forecast["time"] == expected_time
        assert first_forecast["value"] == 0.28

    def test_price_sensor_forecast_uses_pricing_mode(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor forecast uses configured pricing mode."""
        subentry = create_mock_subentry(pricing_mode=PRICING_MODE_APP)

        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        attrs = sensor.extra_state_attributes
        # APP mode should use advanced_price_predicted for forecast values
        assert attrs["forecast"][0]["value"] == 0.28

    def test_price_sensor_feed_in_negates_forecast(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test feed-in price sensor negates forecast values."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_FEED_IN,
        )

        attrs = sensor.extra_state_attributes
        # Feed-in forecast values should be negated (default is APP mode)
        assert attrs["forecast"][0]["value"] == -0.12


class TestAmberDetailedPriceSensor:
    """Tests for AmberDetailedPriceSensor."""

    def test_detailed_price_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test detailed price sensor initialization."""
        sensor = AmberDetailedPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_{CHANNEL_GENERAL}_price_detailed"
        assert sensor._attr_translation_key == "general_price_detailed"

    def test_detailed_price_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test detailed price sensor returns current price."""
        # Use AEMO mode to test per_kwh
        subentry = create_mock_subentry(pricing_mode="aemo")

        sensor = AmberDetailedPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        # AEMO mode uses per_kwh
        assert sensor.native_value == 0.25

    def test_detailed_price_sensor_feed_in_negated(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test feed-in detailed price is negated."""
        subentry = create_mock_subentry(pricing_mode="aemo")

        sensor = AmberDetailedPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_FEED_IN,
        )

        # Feed-in price is negated
        assert sensor.native_value == -0.10

    def test_detailed_price_sensor_no_data(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test detailed price sensor with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)
        coordinator.get_forecasts = MagicMock(return_value=[])
        coordinator.data_source = "polling"

        sensor = AmberDetailedPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_detailed_price_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test detailed price sensor extra attributes."""
        sensor = AmberDetailedPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        attrs = sensor.extra_state_attributes
        assert ATTR_FORECASTS in attrs
        assert len(attrs[ATTR_FORECASTS]) == 2
        assert attrs["data_source"] == "polling"

    def test_detailed_price_sensor_feed_in_inverts_prices(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test feed-in detailed price sensor inverts all prices in attributes."""
        sensor = AmberDetailedPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_FEED_IN,
        )

        attrs = sensor.extra_state_attributes
        forecasts = attrs[ATTR_FORECASTS]
        # Original price is 0.11, should be -0.11 after inversion
        assert forecasts[0][ATTR_PER_KWH] == -0.11

    def test_detailed_price_sensor_disabled_by_default(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test detailed price sensor is disabled by default."""
        sensor = AmberDetailedPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor._attr_entity_registry_enabled_default is False

    def test_detailed_price_sensor_uses_pricing_mode(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test detailed price sensor uses configured pricing mode."""
        subentry = create_mock_subentry(pricing_mode=PRICING_MODE_APP)

        # Add advanced price to mock data
        mock_coordinator_with_data.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: 0.25,
                ATTR_ADVANCED_PRICE: 0.28,
            }
        )

        sensor = AmberDetailedPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        # APP pricing mode uses advanced_price_predicted
        assert sensor.native_value == 0.28


class TestAmberForecastPriceSensor:
    """Tests for AmberForecastPriceSensor."""

    def test_forecast_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast sensor initialization."""
        sensor = AmberForecastPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
            forecast_source=FORECAST_SOURCE_AEMO,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_{CHANNEL_GENERAL}_forecast_aemo"
        assert sensor._attr_translation_key == "general_forecast_aemo"
        assert sensor._attr_entity_registry_enabled_default is False

    def test_forecast_sensor_native_value_aemo(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast sensor returns per_kwh for AEMO."""
        sensor = AmberForecastPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
            forecast_source=FORECAST_SOURCE_AEMO,
        )

        assert sensor.native_value == 0.25

    def test_forecast_sensor_native_value_advanced_prices(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast sensor reads advanced price variants."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: 0.25,
                ATTR_ADVANCED_PRICE: {"low": 0.20, "predicted": 0.23, "high": 0.30},
            }
        )
        coordinator.get_forecasts = MagicMock(return_value=[])
        coordinator.data_source = "polling"

        predicted_sensor = AmberForecastPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
            forecast_source=FORECAST_SOURCE_AMBER_PREDICTED,
        )
        low_sensor = AmberForecastPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
            forecast_source=FORECAST_SOURCE_AMBER_LOW,
        )
        high_sensor = AmberForecastPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
            forecast_source=FORECAST_SOURCE_AMBER_HIGH,
        )

        assert predicted_sensor.native_value == 0.23
        assert low_sensor.native_value == 0.20
        assert high_sensor.native_value == 0.30

    def test_forecast_sensor_feed_in_aemo_negated_state(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test feed-in forecast sensor negates AEMO state."""
        sensor = AmberForecastPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_FEED_IN,
            forecast_source=FORECAST_SOURCE_AEMO,
        )

        assert sensor.native_value == -0.10

    def test_forecast_sensor_feed_in_negates_forecast(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test feed-in forecast sensor negates forecast values."""
        sensor = AmberForecastPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_FEED_IN,
            forecast_source=FORECAST_SOURCE_AMBER_PREDICTED,
        )

        attrs = sensor.extra_state_attributes
        assert attrs["forecast"][0]["value"] == -0.12


class TestAmberRenewablesSensor:
    """Tests for AmberRenewablesSensor."""

    def test_renewables_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test renewables sensor initialization."""
        sensor = AmberRenewablesSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_renewables"
        assert sensor._attr_translation_key == "renewables"
        assert sensor._attr_native_unit_of_measurement == "%"

    def test_renewables_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test renewables sensor returns correct value."""
        sensor = AmberRenewablesSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == 45.5


class TestAmberSiteSensor:
    """Tests for AmberSiteSensor."""

    def test_site_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test site sensor initialization."""
        sensor = AmberSiteSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_site"
        assert sensor._attr_translation_key == "site"

    def test_site_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test site sensor returns network name."""
        sensor = AmberSiteSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "Ausgrid"

    def test_site_sensor_is_diagnostic(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test site sensor is a diagnostic entity."""
        from homeassistant.const import EntityCategory  # noqa: PLC0415

        sensor = AmberSiteSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_site_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test site sensor returns site info as attributes."""
        sensor = AmberSiteSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        attrs = sensor.extra_state_attributes
        # Should return raw site_info from coordinator
        assert attrs["network"] == "Ausgrid"
        assert attrs["nmi"] == "1234567890"
        assert attrs["status"] == "active"
        assert attrs["interval_length"] == 30
        assert len(attrs["channels"]) == 2


class TestAmberBaseSensor:
    """Tests for AmberBaseSensor."""

    def test_base_sensor_device_info(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test base sensor device info."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        device_info = sensor.device_info
        assert device_info["manufacturer"] == "Amber Electric"
        assert device_info["configuration_url"] == "https://app.amber.com.au"

    def test_base_sensor_uses_subentry_site_name(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test base sensor uses subentry site name."""
        subentry = create_mock_subentry(site_name="My Home")

        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor._site_name == "My Home"
        assert sensor._attr_translation_key == "general_price"


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    async def test_setup_entry_creates_sensors(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_coordinator_with_data: MagicMock,
        mock_subentry: MagicMock,  # noqa: ARG002 - required for fixture
    ) -> None:
        """Test async_setup_entry creates expected sensors."""
        mock_config_entry.add_to_hass(hass)

        # Set up runtime data
        mock_config_entry.runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=mock_coordinator_with_data,
                )
            }
        )

        added_entities: list = []

        def mock_add_entities(entities: list, *, config_subentry_id: str | None = None) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # With general and feed_in enabled, we should have:
        # 2 channels x 2 sensors (price, detailed price) = 4
        # 2 channels x 4 forecast sensors = 8
        # + renewables + site + polling_stats + api_status + confirmation_lag
        # + rate_limit_remaining + rate_limit_reset + next_poll = 20
        assert len(added_entities) == 20

    async def test_setup_entry_uses_site_channels(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,  # noqa: ARG002 - required for fixture
    ) -> None:
        """Test async_setup_entry creates sensors based on site channels."""
        # Coordinator with only general channel
        coordinator = MagicMock()
        coordinator.get_site_info = MagicMock(
            return_value=Site(
                id="test_site",
                nmi="1234567890",
                network="Ausgrid",
                status=SiteStatus.ACTIVE,
                channels=[Channel(identifier="E1", type=ChannelType.GENERAL, tariff="EA116")],
                interval_length=30,
            )
        )

        mock_config_entry.add_to_hass(hass)
        mock_config_entry.runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=coordinator,
                )
            }
        )

        added_entities: list = []

        def mock_add_entities(entities: list, *, config_subentry_id: str | None = None) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # With only general channel:
        # 1 channel x 2 sensors + 4 forecast sensors
        # + renewables + site + polling_stats + api_status + confirmation_lag
        # + rate_limit_remaining + rate_limit_reset + next_poll = 14
        assert len(added_entities) == 14

    async def test_setup_entry_controlled_load_channel(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,  # noqa: ARG002 - required for fixture
    ) -> None:
        """Test async_setup_entry with controlled load channel only."""
        # Coordinator with only controlled load channel
        coordinator = MagicMock()
        coordinator.get_site_info = MagicMock(
            return_value=Site(
                id="test_site",
                nmi="1234567890",
                network="Ausgrid",
                status=SiteStatus.ACTIVE,
                channels=[Channel(identifier="E1", type=ChannelType.CONTROLLEDLOAD, tariff="EA029")],
                interval_length=30,
            )
        )

        mock_config_entry.add_to_hass(hass)
        mock_config_entry.runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=coordinator,
                )
            }
        )

        added_entities: list = []

        def mock_add_entities(entities: list, *, config_subentry_id: str | None = None) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # With only controlled load channel:
        # 1 channel x 2 sensors + renewables + site + polling_stats + api_status + confirmation_lag
        # + rate_limit_remaining + rate_limit_reset + next_poll = 10
        assert len(added_entities) == 10


class TestAmberPollingStatsSensor:
    """Tests for AmberPollingStatsSensor."""

    def test_polling_stats_sensor_native_value_with_observation(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test polling stats sensor returns last confirmed elapsed time."""
        from custom_components.amber_express.cdf_polling import CDFPollingStats  # noqa: PLC0415

        coordinator = MagicMock()
        coordinator.get_cdf_polling_stats = MagicMock(
            return_value=CDFPollingStats(
                observation_count=100,
                scheduled_polls=[21.0, 27.0, 33.0, 39.0],
                next_poll_index=0,
                confirmatory_poll_count=2,
                polls_per_interval=4,
                last_observation={"start": 15.0, "end": 27.5},
            )
        )

        sensor = AmberPollingStatsSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        # native_value should be the last_observation["end"]
        assert sensor.native_value == 27.5

    def test_polling_stats_sensor_native_value_no_observation(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test polling stats sensor returns None when no observation."""
        from custom_components.amber_express.cdf_polling import CDFPollingStats  # noqa: PLC0415

        coordinator = MagicMock()
        coordinator.get_cdf_polling_stats = MagicMock(
            return_value=CDFPollingStats(
                observation_count=0,
                scheduled_polls=[],
                next_poll_index=0,
                confirmatory_poll_count=0,
                polls_per_interval=4,
                last_observation=None,
            )
        )

        sensor = AmberPollingStatsSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value is None


class TestAmberConfirmationLagSensor:
    """Tests for AmberConfirmationLagSensor."""

    def test_confirmation_lag_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test confirmation lag sensor initialization."""
        sensor = AmberConfirmationLagSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_confirmation_lag"
        assert sensor._attr_translation_key == "confirmation_lag"
        assert sensor._attr_native_unit_of_measurement == "s"

    def test_confirmation_lag_sensor_is_diagnostic(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test confirmation lag sensor is a diagnostic entity."""
        from homeassistant.const import EntityCategory  # noqa: PLC0415

        sensor = AmberConfirmationLagSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_confirmation_lag_sensor_no_observation(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test confirmation lag sensor with no observation returns None."""
        # Default mock has last_estimate_elapsed=None
        sensor = AmberConfirmationLagSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value is None

    def test_confirmation_lag_sensor_with_observation(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test confirmation lag sensor calculates gap from observation."""
        from custom_components.amber_express.cdf_polling import CDFPollingStats  # noqa: PLC0415

        coordinator = MagicMock()
        coordinator.get_cdf_polling_stats = MagicMock(
            return_value=CDFPollingStats(
                observation_count=100,
                scheduled_polls=[21.0, 27.0, 33.0, 39.0],
                next_poll_index=0,
                confirmatory_poll_count=2,
                polls_per_interval=4,
                last_observation={"start": 15.0, "end": 27.5},
            )
        )

        sensor = AmberConfirmationLagSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        # Lag is confirmed - estimate = 27.5 - 15.0 = 12.5
        assert sensor.native_value == 12.5


class TestChannelTranslationKeys:
    """Tests for channel translation key constants."""

    def test_channel_price_translation_keys(self) -> None:
        """Test channel price translation key mapping."""
        assert CHANNEL_PRICE_TRANSLATION_KEY[CHANNEL_GENERAL] == "general_price"
        assert CHANNEL_PRICE_TRANSLATION_KEY[CHANNEL_FEED_IN] == "feed_in_price"
        assert CHANNEL_PRICE_TRANSLATION_KEY[CHANNEL_CONTROLLED_LOAD] == "controlled_load_price"

    def test_channel_price_detailed_translation_keys(self) -> None:
        """Test channel price detailed translation key mapping."""
        assert CHANNEL_PRICE_DETAILED_TRANSLATION_KEY[CHANNEL_GENERAL] == "general_price_detailed"
        assert CHANNEL_PRICE_DETAILED_TRANSLATION_KEY[CHANNEL_FEED_IN] == "feed_in_price_detailed"
        assert CHANNEL_PRICE_DETAILED_TRANSLATION_KEY[CHANNEL_CONTROLLED_LOAD] == "controlled_load_price_detailed"


class TestAmberApiStatusSensor:
    """Tests for AmberApiStatusSensor."""

    def test_api_status_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor initialization."""
        sensor = AmberApiStatusSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_api_status"
        assert sensor._attr_translation_key == "api_status"

    def test_api_status_sensor_is_diagnostic(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor is a diagnostic entity."""
        from homeassistant.const import EntityCategory  # noqa: PLC0415

        sensor = AmberApiStatusSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_api_status_sensor_status_200(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor when status is 200 (OK)."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=200)
        coordinator.get_rate_limit_info = MagicMock(
            return_value={
                "limit": 50,
                "remaining": 45,
                "reset_at": datetime.now(UTC) + timedelta(seconds=300),
                "window_seconds": 300,
                "policy": "50;w=300",
            }
        )

        sensor = AmberApiStatusSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "OK"
        attrs = sensor.extra_state_attributes
        assert attrs["status_code"] == 200
        assert attrs["rate_limit_quota"] == 50
        assert attrs["rate_limit_remaining"] == 45
        assert "rate_limit_reset_at" in attrs  # ISO format datetime string
        assert attrs["rate_limit_window_seconds"] == 300
        assert attrs["rate_limit_policy"] == "50;w=300"

    def test_api_status_sensor_429_error(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor with 429 error."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=429)
        coordinator.get_rate_limit_info = MagicMock(
            return_value={
                "limit": 50,
                "remaining": 0,
                "reset_at": datetime.now(UTC) + timedelta(seconds=120),
                "window_seconds": 300,
                "policy": "50;w=300",
            }
        )

        sensor = AmberApiStatusSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "Too Many Requests"
        attrs = sensor.extra_state_attributes
        assert attrs["status_code"] == 429
        assert attrs["rate_limit_remaining"] == 0

    def test_api_status_sensor_500_error(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor with 500 error."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=500)
        coordinator.get_rate_limit_info = MagicMock(return_value={})

        sensor = AmberApiStatusSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "Internal Server Error"
        assert sensor.extra_state_attributes["status_code"] == 500

    def test_api_status_sensor_unknown_status_code(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor with unknown status code."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=999)
        coordinator.get_rate_limit_info = MagicMock(return_value={})

        sensor = AmberApiStatusSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "Unknown Error"
        assert sensor.extra_state_attributes["status_code"] == 999

    def test_get_http_status_label_common_codes(self) -> None:
        """Test _get_http_status_label for common HTTP status codes."""
        assert AmberApiStatusSensor._get_http_status_label(400) == "Bad Request"
        assert AmberApiStatusSensor._get_http_status_label(401) == "Unauthorized"
        assert AmberApiStatusSensor._get_http_status_label(403) == "Forbidden"
        assert AmberApiStatusSensor._get_http_status_label(404) == "Not Found"
        assert AmberApiStatusSensor._get_http_status_label(429) == "Too Many Requests"
        assert AmberApiStatusSensor._get_http_status_label(500) == "Internal Server Error"
        assert AmberApiStatusSensor._get_http_status_label(502) == "Bad Gateway"
        assert AmberApiStatusSensor._get_http_status_label(503) == "Service Unavailable"


class TestAmberRateLimitRemainingSensor:
    """Tests for AmberRateLimitRemainingSensor."""

    def test_rate_limit_remaining_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit remaining sensor initialization."""
        sensor = AmberRateLimitRemainingSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_rate_limit_remaining"
        assert sensor._attr_translation_key == "rate_limit_remaining"
        assert sensor._attr_native_unit_of_measurement == "requests"

    def test_rate_limit_remaining_sensor_is_diagnostic(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit remaining sensor is a diagnostic entity."""
        from homeassistant.const import EntityCategory  # noqa: PLC0415

        sensor = AmberRateLimitRemainingSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_rate_limit_remaining_sensor_disabled_by_default(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit remaining sensor is disabled by default."""
        sensor = AmberRateLimitRemainingSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_registry_enabled_default is False

    def test_rate_limit_remaining_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit remaining sensor returns correct value."""
        sensor = AmberRateLimitRemainingSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == 45

    def test_rate_limit_remaining_sensor_no_data(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit remaining sensor with no rate limit data."""
        coordinator = MagicMock()
        coordinator.get_rate_limit_info = MagicMock(return_value={})

        sensor = AmberRateLimitRemainingSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value is None


class TestAmberRateLimitResetSensor:
    """Tests for AmberRateLimitResetSensor."""

    def test_rate_limit_reset_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit reset sensor initialization."""
        from homeassistant.components.sensor import SensorDeviceClass  # noqa: PLC0415

        sensor = AmberRateLimitResetSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_rate_limit_reset"
        assert sensor._attr_translation_key == "rate_limit_reset"
        assert sensor._attr_device_class == SensorDeviceClass.TIMESTAMP

    def test_rate_limit_reset_sensor_is_diagnostic(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit reset sensor is a diagnostic entity."""
        from homeassistant.const import EntityCategory  # noqa: PLC0415

        sensor = AmberRateLimitResetSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_rate_limit_reset_sensor_disabled_by_default(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit reset sensor is disabled by default."""
        sensor = AmberRateLimitResetSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_registry_enabled_default is False

    def test_rate_limit_reset_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit reset sensor returns datetime value."""
        sensor = AmberRateLimitResetSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        # Should return a datetime object
        assert isinstance(sensor.native_value, datetime)

    def test_rate_limit_reset_sensor_no_data(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit reset sensor with no rate limit data."""
        coordinator = MagicMock()
        coordinator.get_rate_limit_info = MagicMock(return_value={})

        sensor = AmberRateLimitResetSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value is None


class TestAmberNextPollSensor:
    """Tests for AmberNextPollSensor."""

    def test_next_poll_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test next poll sensor initialization."""
        from homeassistant.components.sensor import SensorDeviceClass  # noqa: PLC0415

        sensor = AmberNextPollSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_next_poll"
        assert sensor._attr_translation_key == "next_poll"
        assert sensor._attr_device_class == SensorDeviceClass.TIMESTAMP

    def test_next_poll_sensor_is_diagnostic(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test next poll sensor is a diagnostic entity."""
        from homeassistant.const import EntityCategory  # noqa: PLC0415

        sensor = AmberNextPollSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_next_poll_sensor_disabled_by_default(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test next poll sensor is disabled by default."""
        sensor = AmberNextPollSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_entity_registry_enabled_default is False

    def test_next_poll_sensor_extra_state_attributes(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test next poll sensor extra attributes."""
        from custom_components.amber_express.cdf_polling import CDFPollingStats  # noqa: PLC0415

        coordinator = MagicMock()
        coordinator.get_cdf_polling_stats = MagicMock(
            return_value=CDFPollingStats(
                observation_count=100,
                scheduled_polls=[21.0, 27.0, 33.0, 39.0],
                next_poll_index=2,
                confirmatory_poll_count=2,
                polls_per_interval=4,
                last_observation={"start": 15.0, "end": 27.5},
            )
        )
        coordinator.get_next_poll_time = MagicMock(return_value=None)

        sensor = AmberNextPollSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        attrs = sensor.extra_state_attributes

        assert attrs["poll_schedule"] == [21.0, 27.0, 33.0, 39.0]
        assert attrs["poll_count"] == 3  # confirmatory_poll_count + 1
