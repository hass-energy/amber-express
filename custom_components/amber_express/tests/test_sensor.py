"""Tests for sensor platform."""

# pyright: reportArgumentType=false, reportOptionalSubscript=false, reportOperatorIssue=false

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from amberelectric.models import Site
from amberelectric.models.channel import Channel
from amberelectric.models.channel_type import ChannelType
from amberelectric.models.site_status import SiteStatus
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData
from custom_components.amber_express.const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DETAILED_FORECAST,
    ATTR_DURATION,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_PER_KWH,
    ATTR_SPOT_PER_KWH,
    ATTR_START_TIME,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_DEMAND_WINDOW_PRICE,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from custom_components.amber_express.sensor import (
    CHANNEL_PRICE_TRANSLATION_KEY,
    SENSOR_DESCRIPTIONS,
    AmberForecastHorizonSensor,
    AmberPriceSensor,
    AmberSensor,
    AmberSensorDescription,
    async_setup_entry,
)
from custom_components.amber_express.utils import get_http_status_label


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


def _get_description(key: str) -> AmberSensorDescription:
    """Look up a sensor description by key."""
    return next(d for d in SENSOR_DESCRIPTIONS if d.key == key)


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

        assert sensor.native_value == -0.10

    def test_price_sensor_native_value_keeps_full_precision(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """The current price is reported at full precision; display precision handles rounding."""
        coordinator = MagicMock()
        coordinator.data_source = "polling"
        coordinator.get_channel_data = MagicMock(return_value={ATTR_PER_KWH: 0.123456})
        coordinator.get_forecasts = MagicMock(return_value=[])

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value == 0.123456

    def test_price_sensor_forecast_value_is_rounded(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """The recorded simple forecast values are rounded to four decimal places."""
        coordinator = MagicMock()
        coordinator.data_source = "polling"
        coordinator.get_channel_data = MagicMock(
            return_value={ATTR_PER_KWH: 0.25, ATTR_START_TIME: "2024-01-01T10:00:00+00:00"}
        )
        coordinator.get_forecasts = MagicMock(
            return_value=[{ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_PER_KWH: 0.123456}]
        )

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.extra_state_attributes["forecast"][0]["value"] == 0.1235

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

        assert sensor.native_value == 0.25

    def test_price_sensor_uses_pricing_mode_app(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor uses advanced_price_predicted when pricing mode is APP."""
        subentry = create_mock_subentry(pricing_mode=PRICING_MODE_APP)

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

        assert sensor.native_value == 0.28

    def test_price_sensor_app_mode_fallback_to_per_kwh(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor falls back to per_kwh when advanced price not available."""
        subentry = create_mock_subentry(pricing_mode=PRICING_MODE_APP)

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
        assert attrs["forecast"][0]["value"] == 0.28

    def test_price_sensor_forecast_aemo_uses_single_value_shape(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test AEMO mode forecasts use single value output."""
        subentry = create_mock_subentry(pricing_mode="aemo")

        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )
        mock_config_entry.subentries = {subentry.subentry_id: subentry}

        first_forecast = sensor.extra_state_attributes["forecast"][0]
        assert first_forecast["value"] == 0.26
        assert set(first_forecast) == {"time", "value"}

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
        assert attrs["forecast"][0]["value"] == -0.12

    def test_price_sensor_rejects_non_numeric_price(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Non-numeric per_kwh values are treated as no price."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: "not-a-number",
                ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
            }
        )
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_price_sensor_adds_demand_window_surcharge(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """General channel applies configured demand window surcharge when flagged."""
        subentry = create_mock_subentry()
        subentry.data[CONF_DEMAND_WINDOW_PRICE] = 0.05
        mock_config_entry.subentries = {subentry.subentry_id: subentry}

        coordinator = MagicMock()
        coordinator.data_source = "polling"
        coordinator.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: 0.25,
                ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
                ATTR_DEMAND_WINDOW: True,
            }
        )
        coordinator.get_forecasts = MagicMock(
            return_value=[
                {
                    ATTR_START_TIME: "2024-01-01T10:05:00+00:00",
                    ATTR_PER_KWH: 0.26,
                    ATTR_DEMAND_WINDOW: True,
                },
            ]
        )

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value == 0.30
        attrs = sensor.extra_state_attributes
        assert attrs["forecast"][0]["value"] == 0.31

    def test_price_sensor_demand_window_surcharge_strips_float_artifacts(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Adding the demand window surcharge stays at the genuine price precision."""
        subentry = create_mock_subentry()
        subentry.data[CONF_DEMAND_WINDOW_PRICE] = 0.2
        mock_config_entry.subentries = {subentry.subentry_id: subentry}

        coordinator = MagicMock()
        coordinator.data_source = "polling"
        coordinator.get_channel_data = MagicMock(return_value={ATTR_PER_KWH: 0.1, ATTR_DEMAND_WINDOW: True})
        coordinator.get_forecasts = MagicMock(return_value=[])

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value == 0.3


class TestAmberPriceSensorDetailedForecast:
    """Tests for the unrecorded detailedForecast attribute on AmberPriceSensor."""

    def test_detailed_forecast_is_unrecorded(self) -> None:
        """The detailedForecast attribute is excluded from the recorder."""
        assert AmberPriceSensor._unrecorded_attributes == frozenset({ATTR_DETAILED_FORECAST})

    def test_detailed_forecast_exposes_full_unmodified_entries(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Detailed forecast exposes full forecast dicts without stripping any fields."""
        forecast_entry = {
            ATTR_START_TIME: "2024-01-01T10:05:00+00:00",
            ATTR_PER_KWH: 0.26,
            ATTR_DURATION: 30,
            ATTR_ESTIMATE: True,
            "descriptor": "neutral",
            "tariff_period": "peak",
            "spike_status": "none",
        }
        coordinator = MagicMock()
        coordinator.data_source = "polling"
        coordinator.get_channel_data = MagicMock(
            return_value={ATTR_PER_KWH: 0.25, ATTR_START_TIME: "2024-01-01T10:00:00+00:00"}
        )
        coordinator.get_forecasts = MagicMock(return_value=[forecast_entry])

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.extra_state_attributes[ATTR_DETAILED_FORECAST] == [forecast_entry]

    def test_detailed_forecast_prices_are_not_rounded(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """The detailedForecast attribute keeps full price precision while the simple forecast rounds."""
        forecast_entry = {
            ATTR_START_TIME: "2024-01-01T10:05:00+00:00",
            ATTR_PER_KWH: 0.123456,
            ATTR_ADVANCED_PRICE: {"low": 0.111111, "predicted": 0.123456, "high": 0.135791},
        }
        coordinator = MagicMock()
        coordinator.data_source = "polling"
        coordinator.get_channel_data = MagicMock(
            return_value={ATTR_PER_KWH: 0.25, ATTR_START_TIME: "2024-01-01T10:00:00+00:00"}
        )
        coordinator.get_forecasts = MagicMock(return_value=[forecast_entry])

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        detailed = sensor.extra_state_attributes[ATTR_DETAILED_FORECAST][0]
        assert detailed[ATTR_PER_KWH] == 0.123456
        assert detailed[ATTR_ADVANCED_PRICE] == {"low": 0.111111, "predicted": 0.123456, "high": 0.135791}

    def test_detailed_forecast_feed_in_negates_prices(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Feed-in detailedForecast negates per_kwh and advanced price values."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_FEED_IN,
        )

        forecast = sensor.extra_state_attributes[ATTR_DETAILED_FORECAST][0]
        assert forecast[ATTR_PER_KWH] == -0.11
        assert forecast[ATTR_SPOT_PER_KWH] == 0.09
        assert forecast[ATTR_ADVANCED_PRICE] == {"low": -0.08, "predicted": -0.12, "high": -0.18}

    def test_detailed_forecast_feed_in_leaves_non_negatable_fields(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Feed-in negation leaves non-numeric and absent price fields untouched."""
        forecast_entry = {
            ATTR_START_TIME: "2024-01-01T10:05:00+00:00",
            ATTR_PER_KWH: "unavailable",
        }
        coordinator = MagicMock()
        coordinator.data_source = "polling"
        coordinator.get_channel_data = MagicMock(
            return_value={ATTR_PER_KWH: 0.10, ATTR_START_TIME: "2024-01-01T10:00:00+00:00"}
        )
        coordinator.get_forecasts = MagicMock(return_value=[forecast_entry])

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_FEED_IN,
        )

        forecast = sensor.extra_state_attributes[ATTR_DETAILED_FORECAST][0]
        assert forecast[ATTR_PER_KWH] == "unavailable"
        assert ATTR_ADVANCED_PRICE not in forecast


class TestAmberRenewablesSensor:
    """Tests for AmberRenewablesSensor (description-driven)."""

    def test_renewables_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test renewables sensor initialization."""
        desc = _get_description("renewables")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_renewables"
        assert sensor.entity_description.translation_key == "renewables"
        assert sensor.entity_description.native_unit_of_measurement == "%"

    def test_renewables_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test renewables sensor returns correct value."""
        desc = _get_description("renewables")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value == 45.5

    def test_renewables_sensor_has_no_extra_state_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Descriptions without attributes_fn return None from extra_state_attributes."""
        desc = _get_description("renewables")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.extra_state_attributes is None


class TestAmberSiteSensor:
    """Tests for AmberSiteSensor (description-driven)."""

    def test_site_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test site sensor initialization."""
        desc = _get_description("site")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_site"
        assert sensor.entity_description.translation_key == "site"

    def test_site_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test site sensor returns network name."""
        desc = _get_description("site")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value == "Ausgrid"

    def test_site_sensor_is_diagnostic(self) -> None:
        """Test site sensor is a diagnostic entity."""
        desc = _get_description("site")
        assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_site_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test site sensor returns site info as attributes."""
        desc = _get_description("site")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        attrs = sensor.extra_state_attributes
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

    def test_get_subentry_option_when_subentry_removed_uses_defaults(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """If the subentry is no longer on the config entry, options fall back to defaults."""
        mock_config_entry.subentries = {}

        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: 0.25,
                ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
            }
        )
        coordinator.get_forecasts = MagicMock(return_value=[])
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value == 0.25


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

        # 2 channels x 1 price sensor + description-driven sensors + forecast_horizon
        assert len(added_entities) == 2 + len(SENSOR_DESCRIPTIONS) + 1

    async def test_setup_entry_uses_site_channels(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,  # noqa: ARG002 - required for fixture
    ) -> None:
        """Test async_setup_entry creates sensors based on site channels."""
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

        # 1 channel x 1 price sensor + description-driven sensors + forecast_horizon
        assert len(added_entities) == 1 + len(SENSOR_DESCRIPTIONS) + 1

    async def test_setup_entry_controlled_load_channel(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,  # noqa: ARG002 - required for fixture
    ) -> None:
        """Test async_setup_entry with controlled load channel only."""
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

        # 1 channel x 1 price sensor + description-driven sensors + forecast_horizon
        assert len(added_entities) == 1 + len(SENSOR_DESCRIPTIONS) + 1

    async def test_setup_entry_no_runtime_data(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """When runtime_data is missing, setup adds no entities."""
        mock_config_entry.add_to_hass(hass)
        mock_config_entry.runtime_data = None

        add_calls: list[bool] = []

        def mock_add_entities(entities: list, *, config_subentry_id: str | None = None) -> None:
            add_calls.append(True)

        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        assert add_calls == []

    async def test_setup_entry_skips_non_site_subentry(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_coordinator_with_data: MagicMock,
    ) -> None:
        """Non-site subentries are skipped."""
        mock_config_entry.add_to_hass(hass)
        other = MagicMock()
        other.subentry_type = "other"
        other.subentry_id = "other_id"
        mock_config_entry.subentries = {"other_id": other}
        mock_config_entry.runtime_data = AmberRuntimeData(
            sites={
                "other_id": SiteRuntimeData(coordinator=mock_coordinator_with_data),
            }
        )

        added_entities: list = []

        def mock_add_entities(entities: list, *, config_subentry_id: str | None = None) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        assert added_entities == []

    async def test_setup_entry_skips_when_site_runtime_missing(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,  # noqa: ARG002
    ) -> None:
        """When sites dict has no entry for the subentry id, that site is skipped."""
        mock_config_entry.add_to_hass(hass)
        mock_config_entry.runtime_data = AmberRuntimeData(sites={})

        added_entities: list = []

        def mock_add_entities(entities: list, *, config_subentry_id: str | None = None) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        assert added_entities == []


class TestAmberPollingStatsSensor:
    """Tests for confirmation delay sensor (description-driven)."""

    def test_polling_stats_sensor_native_value_with_observation(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test polling stats sensor returns last confirmed elapsed time."""
        from custom_components.amber_express.polling import CDFPollingStats  # noqa: PLC0415

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

        desc = _get_description("confirmation_delay")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value == 27.5

    def test_polling_stats_sensor_native_value_no_observation(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test polling stats sensor returns None when no observation."""
        from custom_components.amber_express.polling import CDFPollingStats  # noqa: PLC0415

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

        desc = _get_description("confirmation_delay")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value is None


class TestAmberConfirmationLagSensor:
    """Tests for confirmation lag sensor (description-driven)."""

    def test_confirmation_lag_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test confirmation lag sensor initialization."""
        desc = _get_description("confirmation_lag")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_confirmation_lag"
        assert sensor.entity_description.translation_key == "confirmation_lag"
        assert sensor.entity_description.native_unit_of_measurement == "s"

    def test_confirmation_lag_sensor_is_diagnostic(self) -> None:
        """Test confirmation lag sensor is a diagnostic entity."""
        desc = _get_description("confirmation_lag")
        assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_confirmation_lag_sensor_no_observation(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test confirmation lag sensor with no observation returns None."""
        desc = _get_description("confirmation_lag")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value is None

    def test_confirmation_lag_sensor_with_observation(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test confirmation lag sensor calculates gap from observation."""
        from custom_components.amber_express.polling import CDFPollingStats  # noqa: PLC0415

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

        desc = _get_description("confirmation_lag")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value == 12.5


class TestChannelTranslationKeys:
    """Tests for channel translation key constants."""

    def test_channel_price_translation_keys(self) -> None:
        """Test channel price translation key mapping."""
        assert CHANNEL_PRICE_TRANSLATION_KEY[CHANNEL_GENERAL] == "general_price"
        assert CHANNEL_PRICE_TRANSLATION_KEY[CHANNEL_FEED_IN] == "feed_in_price"
        assert CHANNEL_PRICE_TRANSLATION_KEY[CHANNEL_CONTROLLED_LOAD] == "controlled_load_price"


class TestAmberApiStatusSensor:
    """Tests for api_status sensor (description-driven)."""

    def test_api_status_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API status sensor initialization."""
        desc = _get_description("api_status")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_api_status"
        assert sensor.entity_description.translation_key == "api_status"

    def test_api_status_sensor_is_diagnostic(self) -> None:
        """Test API status sensor is a diagnostic entity."""
        desc = _get_description("api_status")
        assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_api_status_sensor_status_200(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API status sensor when status is 200 (OK)."""
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

        desc = _get_description("api_status")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value == "OK"
        attrs = sensor.extra_state_attributes
        assert attrs["status_code"] == 200
        assert attrs["rate_limit_quota"] == 50
        assert attrs["rate_limit_remaining"] == 45
        assert "rate_limit_reset_at" in attrs
        assert attrs["rate_limit_window_seconds"] == 300
        assert attrs["rate_limit_policy"] == "50;w=300"

    def test_api_status_sensor_429_error(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API status sensor with 429 error."""
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

        desc = _get_description("api_status")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
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
        """Test API status sensor with 500 error."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=500)
        coordinator.get_rate_limit_info = MagicMock(return_value={})

        desc = _get_description("api_status")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value == "Internal Server Error"
        assert sensor.extra_state_attributes["status_code"] == 500

    def test_api_status_sensor_unknown_status_code(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API status sensor with unknown status code."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=999)
        coordinator.get_rate_limit_info = MagicMock(return_value={})

        desc = _get_description("api_status")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value == "Unknown Error"
        assert sensor.extra_state_attributes["status_code"] == 999

    def test_get_http_status_label_common_codes(self) -> None:
        """Test get_http_status_label for common HTTP status codes."""
        assert get_http_status_label(400) == "Bad Request"
        assert get_http_status_label(401) == "Unauthorized"
        assert get_http_status_label(403) == "Forbidden"
        assert get_http_status_label(404) == "Not Found"
        assert get_http_status_label(429) == "Too Many Requests"
        assert get_http_status_label(500) == "Internal Server Error"
        assert get_http_status_label(502) == "Bad Gateway"
        assert get_http_status_label(503) == "Service Unavailable"


class TestAmberRateLimitRemainingSensor:
    """Tests for rate_limit_remaining sensor (description-driven)."""

    def test_rate_limit_remaining_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit remaining sensor initialization."""
        desc = _get_description("rate_limit_remaining")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_rate_limit_remaining"
        assert sensor.entity_description.translation_key == "rate_limit_remaining"
        assert sensor.entity_description.native_unit_of_measurement == "requests"

    def test_rate_limit_remaining_sensor_is_diagnostic(self) -> None:
        """Test rate limit remaining sensor is a diagnostic entity."""
        desc = _get_description("rate_limit_remaining")
        assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_rate_limit_remaining_sensor_disabled_by_default(self) -> None:
        """Test rate limit remaining sensor is disabled by default."""
        desc = _get_description("rate_limit_remaining")
        assert desc.entity_registry_enabled_default is False

    def test_rate_limit_remaining_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit remaining sensor returns correct value."""
        desc = _get_description("rate_limit_remaining")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
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

        desc = _get_description("rate_limit_remaining")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value is None


class TestAmberRateLimitResetSensor:
    """Tests for rate_limit_reset sensor (description-driven)."""

    def test_rate_limit_reset_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit reset sensor initialization."""
        desc = _get_description("rate_limit_reset")

        assert desc.device_class == SensorDeviceClass.TIMESTAMP
        assert desc.translation_key == "rate_limit_reset"

        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_rate_limit_reset"

    def test_rate_limit_reset_sensor_is_diagnostic(self) -> None:
        """Test rate limit reset sensor is a diagnostic entity."""
        desc = _get_description("rate_limit_reset")
        assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_rate_limit_reset_sensor_disabled_by_default(self) -> None:
        """Test rate limit reset sensor is disabled by default."""
        desc = _get_description("rate_limit_reset")
        assert desc.entity_registry_enabled_default is False

    def test_rate_limit_reset_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit reset sensor returns datetime value."""
        desc = _get_description("rate_limit_reset")
        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert isinstance(sensor.native_value, datetime)

    def test_rate_limit_reset_sensor_no_data(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test rate limit reset sensor with no rate limit data."""
        coordinator = MagicMock()
        coordinator.get_rate_limit_info = MagicMock(return_value={})

        desc = _get_description("rate_limit_reset")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.native_value is None


class TestAmberNextPollSensor:
    """Tests for next_poll sensor (description-driven)."""

    def test_next_poll_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test next poll sensor initialization."""
        desc = _get_description("next_poll")

        assert desc.device_class == SensorDeviceClass.TIMESTAMP
        assert desc.translation_key == "next_poll"

        sensor = AmberSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_next_poll"

    def test_next_poll_sensor_is_diagnostic(self) -> None:
        """Test next poll sensor is a diagnostic entity."""
        desc = _get_description("next_poll")
        assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_next_poll_sensor_disabled_by_default(self) -> None:
        """Test next poll sensor is disabled by default."""
        desc = _get_description("next_poll")
        assert desc.entity_registry_enabled_default is False

    def test_next_poll_sensor_extra_state_attributes(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test next poll sensor extra attributes."""
        from custom_components.amber_express.polling import CDFPollingStats  # noqa: PLC0415

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

        desc = _get_description("next_poll")
        sensor = AmberSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        attrs = sensor.extra_state_attributes

        assert attrs["poll_schedule"] == [21.0, 27.0, 33.0, 39.0]
        assert attrs["poll_count"] == 3


class TestAmberForecastHorizonSensor:
    """Tests for forecast horizon diagnostic sensor."""

    def test_forecast_horizon_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon sensor initialization."""
        sensor = AmberForecastHorizonSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_forecast_horizon"
        assert sensor._attr_translation_key == "forecast_horizon"
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC
        assert sensor._attr_native_unit_of_measurement == "h"
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT
        assert sensor._attr_suggested_display_precision == 0
        assert not hasattr(sensor, "_attr_device_class") or sensor._attr_device_class != SensorDeviceClass.TIMESTAMP

    def test_forecast_horizon_returns_hours(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon returns hours from forecasts_timestamp to latest end_time."""
        coordinator = MagicMock()
        coordinator.get_forecasts_timestamp.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        coordinator.get_forecasts = MagicMock(
            return_value=[
                {ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: "2024-01-01T10:30:00+00:00"},
                {ATTR_START_TIME: "2024-01-01T10:30:00+00:00", ATTR_END_TIME: "2024-01-01T22:00:00+00:00"},
            ]
        )

        sensor = AmberForecastHorizonSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == 12.0

    def test_forecast_horizon_returns_fractional_hours(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon returns fractional hours."""
        coordinator = MagicMock()
        coordinator.get_forecasts_timestamp.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        coordinator.get_forecasts = MagicMock(
            return_value=[
                {ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: "2024-01-01T10:15:00+00:00"},
            ]
        )

        sensor = AmberForecastHorizonSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == 0.25

    def test_forecast_horizon_ignores_invalid_end_times(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon skips forecasts with invalid end timestamps."""
        coordinator = MagicMock()
        coordinator.get_forecasts_timestamp.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        coordinator.get_forecasts = MagicMock(
            return_value=[
                {ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: None},
                {ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_END_TIME: "not-a-datetime"},
                {ATTR_START_TIME: "2024-01-01T10:10:00+00:00", ATTR_END_TIME: "2024-01-01T10:15:00+00:00"},
            ]
        )

        sensor = AmberForecastHorizonSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == 0.25

    def test_forecast_horizon_returns_none_for_empty_forecasts(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon returns None when there are no forecasts."""
        coordinator = MagicMock()
        coordinator.get_forecasts_timestamp.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        coordinator.get_forecasts = MagicMock(return_value=[])

        sensor = AmberForecastHorizonSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value is None

    def test_forecast_horizon_returns_none_when_no_forecasts_timestamp(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon returns None when forecasts_timestamp is not set."""
        coordinator = MagicMock()
        coordinator.get_forecasts_timestamp.return_value = None
        coordinator.get_forecasts = MagicMock(
            return_value=[
                {ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: "2024-01-01T10:30:00+00:00"},
            ]
        )

        sensor = AmberForecastHorizonSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value is None

    def test_forecast_horizon_uses_latest_end_across_channels(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon takes max across all channels."""
        coordinator = MagicMock()
        coordinator.get_forecasts_timestamp.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)

        def get_forecasts_for_channel(channel: str) -> list[dict[str, str]]:
            if channel == CHANNEL_GENERAL:
                return [{ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: "2024-01-01T10:30:00+00:00"}]
            if channel == CHANNEL_CONTROLLED_LOAD:
                return [{ATTR_START_TIME: "2024-01-01T10:30:00+00:00", ATTR_END_TIME: "2024-01-01T11:00:00+00:00"}]
            return [{ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: "2024-01-01T10:45:00+00:00"}]

        coordinator.get_forecasts = MagicMock(side_effect=get_forecasts_for_channel)

        sensor = AmberForecastHorizonSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == 1.0

    def test_forecast_horizon_exposes_forecast_end_attribute(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon exposes the raw end datetime as an attribute."""
        coordinator = MagicMock()
        coordinator.get_forecasts_timestamp.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        coordinator.get_forecasts = MagicMock(
            return_value=[
                {ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: "2024-01-01T22:00:00+00:00"},
            ]
        )

        sensor = AmberForecastHorizonSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        attrs = sensor.extra_state_attributes
        assert attrs["forecast_end"] == "2024-01-01T22:00:00+00:00"

    def test_forecast_horizon_no_attributes_when_no_forecasts(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test forecast horizon returns empty attributes when no forecasts."""
        coordinator = MagicMock()
        coordinator.get_forecasts_timestamp.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        coordinator.get_forecasts = MagicMock(return_value=[])

        sensor = AmberForecastHorizonSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.extra_state_attributes == {}


class TestSensorDescriptions:
    """Tests for sensor description metadata."""

    def test_renewables_description(self) -> None:
        """Test renewables sensor description metadata."""
        desc = _get_description("renewables")
        assert desc.device_class == SensorDeviceClass.POWER_FACTOR
        assert desc.state_class == SensorStateClass.MEASUREMENT
        assert desc.native_unit_of_measurement == PERCENTAGE
        assert desc.suggested_display_precision == 1

    def test_confirmation_delay_description(self) -> None:
        """Test confirmation delay sensor description metadata."""
        desc = _get_description("confirmation_delay")
        assert desc.state_class == SensorStateClass.MEASUREMENT
        assert desc.native_unit_of_measurement == "s"
        assert desc.suggested_display_precision == 1
        assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_confirmation_lag_description(self) -> None:
        """Test confirmation lag sensor description metadata."""
        desc = _get_description("confirmation_lag")
        assert desc.state_class == SensorStateClass.MEASUREMENT
        assert desc.native_unit_of_measurement == "s"
        assert desc.suggested_display_precision == 1
        assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_rate_limit_remaining_description(self) -> None:
        """Test rate limit remaining sensor description metadata."""
        desc = _get_description("rate_limit_remaining")
        assert desc.native_unit_of_measurement == "requests"
        assert desc.entity_category == EntityCategory.DIAGNOSTIC
        assert desc.entity_registry_enabled_default is False

    def test_all_descriptions_have_unique_keys(self) -> None:
        """Test that all sensor descriptions have unique keys."""
        keys = [d.key for d in SENSOR_DESCRIPTIONS]
        assert len(keys) == len(set(keys))
