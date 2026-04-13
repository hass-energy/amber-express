"""Tests for binary sensor platform."""

# pyright: reportArgumentType=false, reportOptionalSubscript=false

from unittest.mock import MagicMock

from amberelectric.models import Site
from amberelectric.models.channel import Channel
from amberelectric.models.channel_type import ChannelType
from amberelectric.models.site_status import SiteStatus
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData
from custom_components.amber_express.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    AmberBinarySensor,
    AmberBinarySensorDescription,
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


def _get_description(key: str) -> AmberBinarySensorDescription:
    """Look up a binary sensor description by key."""
    return next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == key)


class TestAmberPriceSpikeSensor:
    """Tests for price spike binary sensor (description-driven)."""

    def test_price_spike_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor initialization."""
        desc = _get_description("price_spike")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_price_spike"
        assert sensor.entity_description.translation_key == "price_spike"

    def test_price_spike_sensor_not_spiking(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor when not spiking."""
        desc = _get_description("price_spike")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
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

        desc = _get_description("price_spike")
        sensor = AmberBinarySensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.is_on is True

    def test_price_spike_sensor_device_info(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test price spike sensor device info."""
        desc = _get_description("price_spike")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
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
        desc = _get_description("price_spike")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
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

        desc = _get_description("price_spike")
        sensor = AmberBinarySensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.extra_state_attributes == {}

    def test_price_spike_sensor_uses_subentry_site_name(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test price spike sensor uses subentry site name."""
        subentry = create_mock_subentry(site_name="My Home")

        desc = _get_description("price_spike")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            description=desc,
        )

        assert sensor._site_name == "My Home"
        assert sensor.entity_description.translation_key == "price_spike"


class TestAmberDemandWindowSensor:
    """Tests for demand window binary sensor (description-driven)."""

    def test_demand_window_sensor_init(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test demand window sensor initialization."""
        desc = _get_description("demand_window")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor._attr_unique_id == f"{mock_subentry.data[CONF_SITE_ID]}_demand_window"
        assert sensor.entity_description.translation_key == "demand_window"

    def test_demand_window_sensor_not_active(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test demand window sensor when not active."""
        desc = _get_description("demand_window")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.is_on is None

    def test_demand_window_sensor_active(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test demand window sensor when active."""
        coordinator = MagicMock()
        coordinator.is_demand_window = MagicMock(return_value=True)

        desc = _get_description("demand_window")
        sensor = AmberBinarySensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.is_on is True

    def test_demand_window_sensor_device_info(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Test demand window sensor device info."""
        desc = _get_description("demand_window")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
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

        desc = _get_description("demand_window")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=subentry,
            description=desc,
        )

        assert sensor._site_name == "My Home"
        assert sensor.entity_description.translation_key == "demand_window"


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

        assert len(added_entities) == len(BINARY_SENSOR_DESCRIPTIONS)
        assert all(isinstance(e, AmberBinarySensor) for e in added_entities)
        keys = {e.entity_description.key for e in added_entities}
        assert keys == {"price_spike", "demand_window"}

    async def test_setup_entry_no_general_channel(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,  # noqa: ARG002 - required for fixture
    ) -> None:
        """Test async_setup_entry with no general channel."""
        coordinator = MagicMock()
        coordinator.get_site_info = MagicMock(
            return_value=Site(
                id="test_site",
                nmi="1234567890",
                network="Ausgrid",
                status=SiteStatus.ACTIVE,
                channels=[Channel(identifier="B1", type=ChannelType.FEEDIN, tariff="EA116")],
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

        assert len(added_entities) == 0

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


class TestPriceSpikeIconAndDemandWindowProperties:
    """Coverage for icon_fn and description-only branches on binary sensors."""

    def test_price_spike_icon_follows_spike_status(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Icons reflect spike status including unknown values falling back to default."""
        desc = _get_description("price_spike")

        for status, expected_icon in (
            ("potential", "mdi:power-plug-outline"),
            ("spike", "mdi:power-plug-off"),
            ("unknown_status", "mdi:power-plug"),
        ):
            coordinator = MagicMock()
            coordinator.get_channel_data = MagicMock(
                return_value={ATTR_SPIKE_STATUS: status, ATTR_DESCRIPTOR: "neutral"}
            )
            sensor = AmberBinarySensor(
                coordinator=coordinator,
                entry=mock_config_entry,
                subentry=mock_subentry,
                description=desc,
            )
            assert sensor.icon == expected_icon

    def test_price_spike_icon_when_no_channel_data(
        self,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Without general channel data, icon falls back to the default spike icon."""
        coordinator = MagicMock()
        coordinator.get_channel_data = MagicMock(return_value=None)
        desc = _get_description("price_spike")
        sensor = AmberBinarySensor(
            coordinator=coordinator,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.icon == "mdi:power-plug"

    def test_demand_window_sensor_icon_and_attributes_none(
        self,
        mock_coordinator_with_data: MagicMock,
        mock_config_entry: MockConfigEntry,
        mock_subentry: MagicMock,
    ) -> None:
        """Demand window has no icon_fn or attributes_fn."""
        desc = _get_description("demand_window")
        sensor = AmberBinarySensor(
            coordinator=mock_coordinator_with_data,
            entry=mock_config_entry,
            subentry=mock_subentry,
            description=desc,
        )

        assert sensor.icon is None
        assert sensor.extra_state_attributes is None
