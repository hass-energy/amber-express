"""Tests for integration setup and unload."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express import async_setup_entry, async_unload_entry, async_update_listener
from custom_components.amber_express.const import (
    CONF_API_TOKEN,
    CONF_ENABLE_WEBSOCKET,
    CONF_FORECAST_INTERVALS,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DEFAULT_FORECAST_INTERVALS,
    DEFAULT_PRICING_MODE,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from custom_components.amber_express.repairs import (
    LEGACY_PRICING_MODE_ALL,
    async_create_fix_flow,
    async_create_legacy_pricing_mode_all_issue,
    issue_id_for_legacy_pricing_mode_all,
)


def create_mock_subentry(
    site_id: str = "test_site",
    site_name: str = "Test",
    subentry_id: str = "test_subentry_id",
    *,
    pricing_mode: str = DEFAULT_PRICING_MODE,
    websocket_enabled: bool = True,
) -> MagicMock:
    """Create a mock subentry."""
    subentry = MagicMock()
    subentry.subentry_type = SUBENTRY_TYPE_SITE
    subentry.subentry_id = subentry_id
    subentry.title = site_name
    subentry.unique_id = site_id
    subentry.data = {
        CONF_SITE_ID: site_id,
        CONF_SITE_NAME: site_name,
        "nmi": "1234567890",
        "network": "Ausgrid",
        "channels": [{"type": "general", "tariff": "EA116", "identifier": "E1"}],
        CONF_PRICING_MODE: pricing_mode,
        CONF_ENABLE_WEBSOCKET: websocket_enabled,
        CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
        CONF_FORECAST_INTERVALS: DEFAULT_FORECAST_INTERVALS,
    }
    return subentry


def create_mock_entry_with_subentry(
    hass: HomeAssistant,
    api_token: str = "test_token",  # noqa: S107
    site_id: str = "test_site",
    site_name: str = "Test",
    *,
    pricing_mode: str = DEFAULT_PRICING_MODE,
    websocket_enabled: bool = True,
) -> MockConfigEntry:
    """Create a mock config entry with a site subentry."""
    subentry = create_mock_subentry(
        site_id=site_id,
        site_name=site_name,
        pricing_mode=pricing_mode,
        websocket_enabled=websocket_enabled,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Amber Electric",
        data={CONF_API_TOKEN: api_token},
        options={},
        unique_id=f"amber_{hash(api_token)}",
    )

    # Mock subentries property
    entry.subentries = {"test_subentry_id": subentry}

    entry.add_to_hass(hass)
    return entry


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    async def test_setup_entry_success(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test successful setup with subentries."""
        entry = create_mock_entry_with_subentry(hass)

        with (
            patch("custom_components.amber_express.AmberDataCoordinator") as mock_coordinator_class,
            patch("custom_components.amber_express.AmberWebSocketClient") as mock_ws_class,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()) as mock_forward,
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.start = AsyncMock()
            mock_coordinator.stop = AsyncMock()
            mock_coordinator.update_from_websocket = MagicMock()
            mock_coordinator_class.return_value = mock_coordinator

            mock_ws = AsyncMock()
            mock_ws.start = AsyncMock()
            mock_ws_class.return_value = mock_ws

            result = await async_setup_entry(hass, entry)

            assert result is True
            assert entry.runtime_data is not None
            assert "test_subentry_id" in entry.runtime_data.sites
            assert entry.runtime_data.sites["test_subentry_id"].coordinator == mock_coordinator
            assert entry.runtime_data.sites["test_subentry_id"].websocket_client == mock_ws

            mock_coordinator.start.assert_called_once()
            mock_ws.start.assert_called_once()
            mock_forward.assert_called_once()

    async def test_setup_entry_without_websocket(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test setup without websocket enabled."""
        entry = create_mock_entry_with_subentry(hass, websocket_enabled=False)

        with (
            patch("custom_components.amber_express.AmberDataCoordinator") as mock_coordinator_class,
            patch("custom_components.amber_express.AmberWebSocketClient") as mock_ws_class,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.start = AsyncMock()
            mock_coordinator.stop = AsyncMock()
            mock_coordinator_class.return_value = mock_coordinator

            result = await async_setup_entry(hass, entry)

            assert result is True
            assert entry.runtime_data.sites["test_subentry_id"].websocket_client is None
            mock_ws_class.assert_not_called()


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry."""

    async def test_unload_entry_success(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test successful unload."""
        entry = create_mock_entry_with_subentry(hass)

        mock_ws = AsyncMock()
        mock_ws.stop = AsyncMock()

        # Set up runtime data as if setup succeeded
        from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData  # noqa: PLC0415

        mock_coordinator = AsyncMock()
        mock_coordinator.stop = AsyncMock()
        entry.runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=mock_coordinator,
                    websocket_client=mock_ws,
                )
            }
        )

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            result = await async_unload_entry(hass, entry)

            assert result is True
            assert entry.runtime_data is None
            mock_coordinator.stop.assert_called_once()
            mock_ws.stop.assert_called_once()

    async def test_unload_entry_without_websocket(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test unload without websocket."""
        entry = create_mock_entry_with_subentry(hass)

        from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData  # noqa: PLC0415

        mock_coordinator = AsyncMock()
        mock_coordinator.stop = AsyncMock()
        entry.runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=mock_coordinator,
                    websocket_client=None,
                )
            }
        )

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            result = await async_unload_entry(hass, entry)

            assert result is True
            mock_coordinator.stop.assert_called_once()

    async def test_unload_entry_failure(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test failed unload preserves runtime data."""
        entry = create_mock_entry_with_subentry(hass)

        from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData  # noqa: PLC0415

        mock_coordinator = AsyncMock()
        mock_coordinator.stop = AsyncMock()
        runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=mock_coordinator,
                    websocket_client=None,
                )
            }
        )
        entry.runtime_data = runtime_data

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=False),
        ):
            result = await async_unload_entry(hass, entry)

            assert result is False
            # Runtime data should be preserved on failure
            assert entry.runtime_data == runtime_data


class TestAsyncUpdateListener:
    """Tests for async_update_listener."""

    async def test_update_listener_reloads_entry(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test update listener triggers reload."""
        entry = create_mock_entry_with_subentry(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new=AsyncMock(),
        ) as mock_reload:
            await async_update_listener(hass, entry)

            mock_reload.assert_called_once_with(entry.entry_id)


class TestLegacyBothPricingModeRepairs:
    """Tests for legacy both pricing mode repair flow."""

    async def test_setup_creates_issue_and_skips_legacy_all_site(self, hass: HomeAssistant) -> None:
        """Test setup creates issue and skips sites using removed both mode."""
        entry = create_mock_entry_with_subentry(hass, pricing_mode=LEGACY_PRICING_MODE_ALL)

        with (
            patch("custom_components.amber_express.AmberDataCoordinator") as mock_coordinator_class,
            patch("custom_components.amber_express.AmberWebSocketClient") as mock_ws_class,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()) as mock_forward,
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        assert entry.runtime_data is not None
        assert "test_subentry_id" not in entry.runtime_data.sites
        mock_coordinator_class.assert_not_called()
        mock_ws_class.assert_not_called()
        mock_forward.assert_called_once()

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN,
            issue_id_for_legacy_pricing_mode_all("test_subentry_id"),
        )
        assert issue is not None

    async def test_repair_flow_migrates_legacy_all_to_app(self, hass: HomeAssistant) -> None:
        """Test repair fix flow migrates legacy both mode to APP."""
        entry = create_mock_entry_with_subentry(hass, pricing_mode=LEGACY_PRICING_MODE_ALL)

        async_create_legacy_pricing_mode_all_issue(
            hass=hass,
            entry_id=entry.entry_id,
            subentry_id="test_subentry_id",
            site_name=entry.subentries["test_subentry_id"].title,
        )

        issue_id = issue_id_for_legacy_pricing_mode_all("test_subentry_id")
        flow = await async_create_fix_flow(
            hass=hass,
            issue_id=issue_id,
            data={"entry_id": entry.entry_id, "subentry_id": "test_subentry_id"},
        )
        flow.hass = hass
        flow.handler = DOMAIN
        flow.issue_id = issue_id

        hass.config_entries.async_update_subentry = MagicMock(
            side_effect=lambda _entry, _subentry, data: setattr(_subentry, "data", data)
        )

        result = await flow.async_step_confirm(user_input={})

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert entry.subentries["test_subentry_id"].data[CONF_PRICING_MODE] == PRICING_MODE_APP
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
