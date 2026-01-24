"""Tests for binary sensor platform."""

# pyright: reportArgumentType=false

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData
from custom_components.amber_express.binary_sensor import (
    AmberDemandWindowSensor,
    AmberPriceSpikeSensor,
    async_setup_entry,
)
from custom_components.amber_express.const import (
    ATTR_DESCRIPTOR,
    ATTR_SPIKE_STATUS,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    SUBENTRY_TYPE_SITE,
)


def create_mock_subentry(
    site_id: str = "test_site_id",
    site_name: str = "Test",
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
    }
    return subentry


class TestAmberPriceSpikeSensor:
    """Tests for AmberPriceSpikeSensor."""

    def test_price_spike_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor initialization."""
        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_price_spike"
        assert sensor._attr_translation_key == "price_spike"

    def test_price_spike_sensor_not_spiking(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor when not spiking."""
        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.is_on is False

    def test_price_spike_sensor_spiking(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor when spiking."""
        coordinator = MagicMock()
        coordinator.is_price_spike = MagicMock(return_value=True)
        coordinator.get_channel_data = MagicMock(return_value={ATTR_SPIKE_STATUS: "spike", ATTR_DESCRIPTOR: "spike"})
        coordinator.data_source = "polling"

        sensor = AmberPriceSpikeSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.is_on is True

    def test_price_spike_sensor_device_info(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor device info."""
        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        device_info = sensor.device_info
        assert device_info["manufacturer"] == "Amber Electric"
        assert device_info["configuration_url"] == "https://app.amber.com.au"

    def test_price_spike_sensor_extra_attributes(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor extra attributes."""
        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        attrs = sensor.extra_state_attributes
        assert attrs[ATTR_SPIKE_STATUS] == "none"
        assert attrs[ATTR_DESCRIPTOR] == "neutral"
        assert attrs["data_source"] == "polling"

    def test_price_spike_sensor_extra_attributes_no_data(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor extra attributes with no data."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)
        coordinator.data_source = "polling"

        sensor = AmberPriceSpikeSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.extra_state_attributes == {}

    def test_price_spike_sensor_uses_subentry_site_name(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price spike sensor uses subentry site name."""
        subentry = create_mock_subentry(site_name="My Home")

        sensor = AmberPriceSpikeSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
        )

        assert sensor._site_name == "My Home"
        assert sensor._attr_translation_key == "price_spike"


class TestAmberDemandWindowSensor:
    """Tests for AmberDemandWindowSensor."""

    def test_demand_window_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test demand window sensor initialization."""
        sensor = AmberDemandWindowSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_demand_window"
        assert sensor._attr_translation_key == "demand_window"

    def test_demand_window_sensor_not_active(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test demand window sensor when not active."""
        sensor = AmberDemandWindowSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        # Mock returns None for demand_window
        assert sensor.is_on is None

    def test_demand_window_sensor_active(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test demand window sensor when active."""
        coordinator = MagicMock()
        coordinator.is_demand_window = MagicMock(return_value=True)

        sensor = AmberDemandWindowSensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        assert sensor.is_on is True

    def test_demand_window_sensor_device_info(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test demand window sensor device info."""
        sensor = AmberDemandWindowSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
        )

        device_info = sensor.device_info
        assert device_info["manufacturer"] == "Amber Electric"

    def test_demand_window_sensor_uses_subentry_site_name(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test demand window sensor uses subentry site name."""
        subentry = create_mock_subentry(site_name="My Home")

        sensor = AmberDemandWindowSensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
        )

        assert sensor._site_name == "My Home"
        assert sensor._attr_translation_key == "demand_window"


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

        # With general enabled, we should have price spike + demand window = 2
        assert len(added_entities) == 2
        assert any(isinstance(e, AmberPriceSpikeSensor) for e in added_entities)
        assert any(isinstance(e, AmberDemandWindowSensor) for e in added_entities)

    async def test_setup_entry_no_general_channel(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,  # noqa: ARG002 - required for fixture
    ) -> None:
        """Test async_setup_entry with no general channel."""
        # Coordinator without general channel
        coordinator = MagicMock()
        coordinator.get_site_info = MagicMock(
            return_value={
                "id": "test_site",
                "network": "Ausgrid",
                "channels": [{"type": "feedIn", "tariff": "EA116"}],  # Only feed-in
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

        # Without general channel, no binary sensors should be created
        assert len(added_entities) == 0
