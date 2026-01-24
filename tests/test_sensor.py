"""Tests for sensor platform."""

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.const import (
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_SPIKE_STATUS,
    ATTR_START_TIME,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_ENABLE_CONTROLLED_LOAD,
    CONF_ENABLE_FEED_IN,
    CONF_ENABLE_GENERAL,
    CONF_SITE_ID,
    CONF_SITE_NAME,
)
from custom_components.amber_express.sensor import (
    CHANNEL_NAMES,
    AmberDescriptorSensor,
    AmberForecastSensor,
    AmberPriceSensor,
    AmberRenewablesSensor,
    AmberTariffSensor,
    async_setup_entry,
)


class TestAmberPriceSensor:
    """Tests for AmberPriceSensor."""

    def test_price_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor initialization."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor._attr_unique_id == f"{mock_config_entry.data[CONF_SITE_ID]}_{CHANNEL_GENERAL}_price"
        assert sensor._attr_name == f"{mock_config_entry.title} - General Price"
        assert sensor._attr_native_unit_of_measurement == "$/kWh"

    def test_price_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor returns correct value."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value == 0.25

    def test_price_sensor_feed_in_negated(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test feed-in price is negated."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_FEED_IN,
        )

        # Feed-in price is negated (earnings shown as negative cost)
        assert sensor.native_value == -0.10

    def test_price_sensor_no_data(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_price_sensor_null_price(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor with null price in data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value={ATTR_PER_KWH: None})
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_price_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor extra attributes."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        attrs = sensor.extra_state_attributes
        assert attrs[ATTR_START_TIME] == "2024-01-01T10:00:00+00:00"
        assert attrs[ATTR_END_TIME] == "2024-01-01T10:05:00+00:00"
        assert attrs[ATTR_ESTIMATE] is False
        assert attrs["data_source"] == "polling"

    def test_price_sensor_extra_attributes_no_data(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor extra attributes with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.extra_state_attributes == {}

    def test_price_sensor_with_advanced_price(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price sensor with advanced_price attribute."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                "advanced_price_predicted": {"low": 0.20, "predicted": 0.25, "high": 0.30},
            }
        )
        coordinator.data_source = "polling"

        sensor = AmberPriceSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        attrs = sensor.extra_state_attributes
        assert "advanced_price_predicted" in attrs


class TestAmberForecastSensor:
    """Tests for AmberForecastSensor."""

    def test_forecast_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test forecast sensor initialization."""
        sensor = AmberForecastSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor._attr_unique_id == f"{mock_config_entry.data[CONF_SITE_ID]}_{CHANNEL_GENERAL}_forecast"
        assert sensor._attr_name == f"{mock_config_entry.title} - General Forecast"

    def test_forecast_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test forecast sensor returns first forecast price."""
        sensor = AmberForecastSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value == 0.26

    def test_forecast_sensor_feed_in_negated(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test feed-in forecast price is negated."""
        sensor = AmberForecastSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_FEED_IN,
        )

        # Feed-in price is negated
        assert sensor.native_value == -0.11

    def test_forecast_sensor_no_forecasts(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test forecast sensor with no forecasts."""
        coordinator = MagicMock()
        coordinator.get_forecasts = MagicMock(return_value=[])
        coordinator.data_source = "polling"

        sensor = AmberForecastSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_forecast_sensor_null_price(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test forecast sensor with null price in first forecast."""
        coordinator = MagicMock()
        coordinator.get_forecasts = MagicMock(return_value=[{ATTR_PER_KWH: None}])
        coordinator.data_source = "polling"

        sensor = AmberForecastSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_forecast_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test forecast sensor extra attributes."""
        sensor = AmberForecastSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        attrs = sensor.extra_state_attributes
        assert ATTR_FORECASTS in attrs
        assert len(attrs[ATTR_FORECASTS]) == 2
        assert attrs["data_source"] == "polling"

    def test_forecast_sensor_feed_in_inverts_prices(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test feed-in forecast sensor inverts all prices in attributes."""
        sensor = AmberForecastSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_FEED_IN,
        )

        attrs = sensor.extra_state_attributes
        forecasts = attrs[ATTR_FORECASTS]
        # Original price is 0.11, should be -0.11 after inversion
        assert forecasts[0][ATTR_PER_KWH] == -0.11


class TestAmberDescriptorSensor:
    """Tests for AmberDescriptorSensor."""

    def test_descriptor_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test descriptor sensor initialization."""
        sensor = AmberDescriptorSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor._attr_unique_id == f"{mock_config_entry.data[CONF_SITE_ID]}_{CHANNEL_GENERAL}_descriptor"
        assert sensor._attr_name == f"{mock_config_entry.title} - General Price Descriptor"

    def test_descriptor_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test descriptor sensor returns correct value."""
        sensor = AmberDescriptorSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value == "neutral"

    def test_descriptor_sensor_no_data(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test descriptor sensor with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)

        sensor = AmberDescriptorSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.native_value is None

    def test_descriptor_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test descriptor sensor extra attributes."""
        sensor = AmberDescriptorSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        attrs = sensor.extra_state_attributes
        assert attrs[ATTR_SPIKE_STATUS] == "none"

    def test_descriptor_sensor_extra_attributes_no_data(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test descriptor sensor extra attributes with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)

        sensor = AmberDescriptorSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor.extra_state_attributes == {}


class TestAmberRenewablesSensor:
    """Tests for AmberRenewablesSensor."""

    def test_renewables_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test renewables sensor initialization."""
        sensor = AmberRenewablesSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        assert sensor._attr_unique_id == f"{mock_config_entry.data[CONF_SITE_ID]}_renewables"
        assert sensor._attr_name == f"{mock_config_entry.title} - Renewables"
        assert sensor._attr_native_unit_of_measurement == "%"

    def test_renewables_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test renewables sensor returns correct value."""
        sensor = AmberRenewablesSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        assert sensor.native_value == 45.5


class TestAmberTariffSensor:
    """Tests for AmberTariffSensor."""

    def test_tariff_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test tariff sensor initialization."""
        sensor = AmberTariffSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        assert sensor._attr_unique_id == f"{mock_config_entry.data[CONF_SITE_ID]}_tariff"
        assert sensor._attr_name == f"{mock_config_entry.title} - Tariff"

    def test_tariff_sensor_native_value(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test tariff sensor returns network name."""
        sensor = AmberTariffSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        assert sensor.native_value == "Ausgrid"

    def test_tariff_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test tariff sensor extra attributes."""
        sensor = AmberTariffSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        attrs = sensor.extra_state_attributes
        assert attrs["network"] == "Ausgrid"
        assert attrs["nmi"] == "1234567890"
        assert attrs["status"] == "active"
        assert attrs["interval_length"] == 30
        assert len(attrs["tariffs"]) == 2
        assert attrs["tariff_count"] == 2
        assert "EA116" in attrs["tariff_codes"]
        assert "EA029" in attrs["tariff_codes"]
        assert attrs["has_general"] is True
        assert attrs["has_feed_in"] is True
        assert attrs["has_controlled_load"] is False
        assert attrs["data_source"] == "polling"

    def test_tariff_sensor_channel_friendly_names(self) -> None:
        """Test channel friendly names mapping."""
        assert AmberTariffSensor.CHANNEL_FRIENDLY_NAMES["general"] == "General"
        assert AmberTariffSensor.CHANNEL_FRIENDLY_NAMES["feedIn"] == "Feed In"
        assert AmberTariffSensor.CHANNEL_FRIENDLY_NAMES["controlledLoad"] == "Controlled Load"

    def test_tariff_sensor_with_tariff_info(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test tariff sensor with full tariff info."""
        coordinator = MagicMock()
        coordinator.data_source = "polling"
        coordinator.get_site_info = MagicMock(
            return_value={
                "network": "Ausgrid",
                "nmi": "1234567890",
                "status": "active",
                "interval_length": 30,
                "channels": [{"type": "general", "tariff": "EA116"}],
            }
        )
        coordinator.get_tariff_info = MagicMock(
            return_value={
                "period": "peak",
                "season": "summer",
                "block": 2,
                "demand_window": True,
            }
        )
        coordinator.get_active_channels = MagicMock(return_value=["general"])

        sensor = AmberTariffSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
        )

        attrs = sensor.extra_state_attributes
        assert attrs["period"] == "peak"
        assert attrs["season"] == "summer"
        assert attrs["block"] == 2
        assert attrs["demand_window"] is True


class TestAmberBaseSensor:
    """Tests for AmberBaseSensor."""

    def test_base_sensor_device_info(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test base sensor device info."""
        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            channel=CHANNEL_GENERAL,
        )

        device_info = sensor.device_info
        assert device_info["manufacturer"] == "Amber Electric"
        assert device_info["configuration_url"] == "https://app.amber.com.au"

    def test_base_sensor_uses_entry_title(
        self,
        mock_coordinator_with_data: MagicMock,
    ) -> None:
        """Test base sensor uses entry title for site name."""
        entry = MockConfigEntry(
            domain="amber_express",
            title="My Home",
            data={
                CONF_SITE_ID: "test_site_id",
            },
            options={},
        )

        sensor = AmberPriceSensor(
            coordinator=mock_coordinator_with_data,
            entry=entry,
            channel=CHANNEL_GENERAL,
        )

        assert sensor._site_name == "My Home"
        assert sensor._attr_name == "My Home - General Price"


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    async def test_setup_entry_creates_sensors(
        self,
        hass,
        mock_config_entry: MockConfigEntry,
        mock_coordinator_with_data: MagicMock,
    ) -> None:
        """Test async_setup_entry creates expected sensors."""
        mock_config_entry.add_to_hass(hass)

        # Set up the domain data
        hass.data["amber_express"] = {
            mock_config_entry.entry_id: {"coordinator": mock_coordinator_with_data}
        }

        added_entities: list = []

        def mock_add_entities(entities: list) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # With general and feed_in enabled, we should have:
        # 2 channels x 3 sensors (price, forecast, descriptor) = 6
        # + renewables + tariff = 8
        assert len(added_entities) == 8

    async def test_setup_entry_respects_channel_options(
        self,
        hass,
        mock_coordinator_with_data: MagicMock,
    ) -> None:
        """Test async_setup_entry respects channel enable options."""
        entry = MockConfigEntry(
            domain="amber_express",
            title="Test",
            data={CONF_SITE_ID: "test_site_id", CONF_SITE_NAME: "Test"},
            options={
                CONF_ENABLE_GENERAL: True,
                CONF_ENABLE_FEED_IN: False,
                CONF_ENABLE_CONTROLLED_LOAD: False,
            },
        )
        entry.add_to_hass(hass)

        hass.data["amber_express"] = {entry.entry_id: {"coordinator": mock_coordinator_with_data}}

        added_entities: list = []

        def mock_add_entities(entities: list) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        # With only general enabled:
        # 1 channel x 3 sensors + renewables + tariff = 5
        assert len(added_entities) == 5

    async def test_setup_entry_controlled_load(
        self,
        hass,
        mock_coordinator_with_data: MagicMock,
    ) -> None:
        """Test async_setup_entry with controlled load enabled."""
        entry = MockConfigEntry(
            domain="amber_express",
            title="Test",
            data={CONF_SITE_ID: "test_site_id", CONF_SITE_NAME: "Test"},
            options={
                CONF_ENABLE_GENERAL: False,
                CONF_ENABLE_FEED_IN: False,
                CONF_ENABLE_CONTROLLED_LOAD: True,
            },
        )
        entry.add_to_hass(hass)

        hass.data["amber_express"] = {entry.entry_id: {"coordinator": mock_coordinator_with_data}}

        added_entities: list = []

        def mock_add_entities(entities: list) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        # With only controlled load enabled:
        # 1 channel x 3 sensors = 3 (no renewables/tariff as general is disabled)
        assert len(added_entities) == 3


class TestChannelNames:
    """Tests for CHANNEL_NAMES constant."""

    def test_channel_names_mapping(self) -> None:
        """Test channel names mapping."""
        assert CHANNEL_NAMES[CHANNEL_GENERAL] == "General"
        assert CHANNEL_NAMES[CHANNEL_FEED_IN] == "Feed In"
        assert CHANNEL_NAMES[CHANNEL_CONTROLLED_LOAD] == "Controlled Load"
