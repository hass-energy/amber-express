"""Tests for sensor platform."""

# pyright: reportArgumentType=false

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
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
    AmberApiStatusSensor,
    AmberDetailedPriceSensor,
    AmberPriceSensor,
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
        assert attrs[ATTR_START_TIME] == "2024-01-01T10:00:00+00:00"
        assert attrs[ATTR_END_TIME] == "2024-01-01T10:05:00+00:00"
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

    def test_price_sensor_with_advanced_price(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price sensor with advanced_price attribute."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(
            return_value={
                ATTR_PER_KWH: 0.25,
                ATTR_ESTIMATE: False,
                ATTR_ADVANCED_PRICE: 0.28,
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

        attrs = sensor.extra_state_attributes
        assert ATTR_ADVANCED_PRICE in attrs

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
        first_forecast = attrs["forecast"][0]
        assert "time" in first_forecast
        assert "value" in first_forecast
        assert first_forecast["time"] == "2024-01-01T10:05:00+00:00"
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
        # + renewables + site + polling_stats + api_status = 8
        assert len(added_entities) == 8

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
            return_value={
                "id": "test_site",
                "network": "Ausgrid",
                "channels": [{"type": "general", "tariff": "EA116"}],
            }
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
        # 1 channel x 2 sensors + renewables + site + polling_stats + api_status = 6
        assert len(added_entities) == 6

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
            return_value={
                "id": "test_site",
                "network": "Ausgrid",
                "channels": [{"type": "controlledLoad", "tariff": "EA029"}],
            }
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
        # 1 channel x 2 sensors + renewables + site + polling_stats + api_status = 6
        assert len(added_entities) == 6


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

        sensor = AmberApiStatusSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "OK"
        assert sensor.extra_state_attributes == {"status_code": 200}

    def test_api_status_sensor_429_error(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor with 429 error."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=429)

        sensor = AmberApiStatusSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "Too Many Requests"
        assert sensor.extra_state_attributes == {"status_code": 429}

    def test_api_status_sensor_500_error(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor with 500 error."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=500)

        sensor = AmberApiStatusSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "Internal Server Error"
        assert sensor.extra_state_attributes == {"status_code": 500}

    def test_api_status_sensor_unknown_status_code(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test API error sensor with unknown status code."""
        coordinator = MagicMock()
        coordinator.get_api_status = MagicMock(return_value=999)

        sensor = AmberApiStatusSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.native_value == "Unknown Error"
        assert sensor.extra_state_attributes == {"status_code": 999}

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
