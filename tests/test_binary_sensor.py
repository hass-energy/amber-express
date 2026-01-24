"""Tests for binary sensor platform."""

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express.binary_sensor import (
    AmberDemandWindowSensor,
    AmberPriceSpikeSensor,
    async_setup_entry,
)
from custom_components.amber_express.const import (
    ATTR_DESCRIPTOR,
    ATTR_SPIKE_STATUS,
    CONF_ENABLE_GENERAL,
    CONF_SITE_ID,
    CONF_SITE_NAME,
)


class TestAmberPriceSpikeSensor:
    """Tests for AmberPriceSpikeSensor."""

    def test_price_spike_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price spike sensor initialization."""
        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        assert sensor._attr_unique_id == f"{mock_config_entry.data[CONF_SITE_ID]}_price_spike"
        assert sensor._attr_name == f"{mock_config_entry.title} - Price Spike"

    def test_price_spike_sensor_not_spiking(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price spike sensor when not spiking."""
        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        assert sensor.is_on is False

    def test_price_spike_sensor_spiking(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price spike sensor when spiking."""
        coordinator = MagicMock()
        coordinator.is_price_spike = MagicMock(return_value=True)
        coordinator.get_channel_data = MagicMock(
            return_value={ATTR_SPIKE_STATUS: "spike", ATTR_DESCRIPTOR: "spike"}
        )
        coordinator.data_source = "polling"

        sensor = AmberPriceSpikeSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
        )

        assert sensor.is_on is True

    def test_price_spike_sensor_device_info(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price spike sensor device info."""
        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        device_info = sensor.device_info
        assert device_info["manufacturer"] == "Amber Electric"
        assert device_info["configuration_url"] == "https://app.amber.com.au"

    def test_price_spike_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price spike sensor extra attributes."""
        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        attrs = sensor.extra_state_attributes
        assert attrs[ATTR_SPIKE_STATUS] == "none"
        assert attrs[ATTR_DESCRIPTOR] == "neutral"
        assert attrs["data_source"] == "polling"

    def test_price_spike_sensor_extra_attributes_no_data(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price spike sensor extra attributes with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)
        coordinator.data_source = "polling"

        sensor = AmberPriceSpikeSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
        )

        assert sensor.extra_state_attributes == {}

    def test_price_spike_sensor_uses_entry_title(
        self,
        mock_coordinator_with_data: MagicMock,
    ) -> None:
        """Test price spike sensor uses entry title for site name."""
        entry = MockConfigEntry(
            domain="amber_express",
            title="My Home",
            data={CONF_SITE_ID: "test_site_id"},
            options={},
        )

        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=entry,
        )

        assert sensor._site_name == "My Home"
        assert sensor._attr_name == "My Home - Price Spike"


class TestAmberDemandWindowSensor:
    """Tests for AmberDemandWindowSensor."""

    def test_demand_window_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test demand window sensor initialization."""
        sensor = AmberDemandWindowSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        assert sensor._attr_unique_id == f"{mock_config_entry.data[CONF_SITE_ID]}_demand_window"
        assert sensor._attr_name == f"{mock_config_entry.title} - Demand Window"

    def test_demand_window_sensor_not_active(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test demand window sensor when not active."""
        sensor = AmberDemandWindowSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        # Mock returns None for demand_window
        assert sensor.is_on is None

    def test_demand_window_sensor_active(
        self,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test demand window sensor when active."""
        coordinator = MagicMock()
        coordinator.is_demand_window = MagicMock(return_value=True)

        sensor = AmberDemandWindowSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
        )

        assert sensor.is_on is True

    def test_demand_window_sensor_device_info(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test demand window sensor device info."""
        sensor = AmberDemandWindowSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
        )

        device_info = sensor.device_info
        assert device_info["manufacturer"] == "Amber Electric"

    def test_demand_window_sensor_uses_entry_title(
        self,
        mock_coordinator_with_data: MagicMock,
    ) -> None:
        """Test demand window sensor uses entry title for site name."""
        entry = MockConfigEntry(
            domain="amber_express",
            title="My Home",
            data={CONF_SITE_ID: "test_site_id"},
            options={},
        )

        sensor = AmberDemandWindowSensor(
            coordinator=mock_coordinator_with_data,
            entry=entry,
        )

        assert sensor._site_name == "My Home"
        assert sensor._attr_name == "My Home - Demand Window"


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

        hass.data["amber_express"] = {
            mock_config_entry.entry_id: {"coordinator": mock_coordinator_with_data}
        }

        added_entities: list = []

        def mock_add_entities(entities: list) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # With general enabled, we should have price spike + demand window = 2
        assert len(added_entities) == 2
        assert any(isinstance(e, AmberPriceSpikeSensor) for e in added_entities)
        assert any(isinstance(e, AmberDemandWindowSensor) for e in added_entities)

    async def test_setup_entry_respects_general_disabled(
        self,
        hass,
        mock_coordinator_with_data: MagicMock,
    ) -> None:
        """Test async_setup_entry respects general channel disabled."""
        entry = MockConfigEntry(
            domain="amber_express",
            title="Test",
            data={CONF_SITE_ID: "test_site_id", CONF_SITE_NAME: "Test"},
            options={CONF_ENABLE_GENERAL: False},
        )
        entry.add_to_hass(hass)

        hass.data["amber_express"] = {entry.entry_id: {"coordinator": mock_coordinator_with_data}}

        added_entities: list = []

        def mock_add_entities(entities: list) -> None:
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        # With general disabled, no binary sensors should be created
        assert len(added_entities) == 0
