"""Tests for integration setup and unload."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express import (
    INTERVAL_CHECK_SECONDS,
    async_setup_entry,
    async_unload_entry,
    async_update_listener,
)
from custom_components.amber_express.const import (
    CONF_API_TOKEN,
    CONF_ENABLE_WEBSOCKET,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DEFAULT_PRICING_MODE,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
    SUBENTRY_TYPE_SITE,
)


def create_mock_subentry(
    site_id: str = "test_site",
    site_name: str = "Test",
    subentry_id: str = "test_subentry_id",
    *,
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
        CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
        CONF_ENABLE_WEBSOCKET: websocket_enabled,
        CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
    }
    return subentry


def create_mock_entry_with_subentry(
    hass: HomeAssistant,
    api_token: str = "test_token",  # noqa: S107
    site_id: str = "test_site",
    site_name: str = "Test",
    *,
    websocket_enabled: bool = True,
) -> MockConfigEntry:
    """Create a mock config entry with a site subentry."""
    subentry = create_mock_subentry(
        site_id=site_id,
        site_name=site_name,
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
            patch("custom_components.amber_express.async_track_time_change") as mock_track_time,
            patch("custom_components.amber_express.async_call_later") as mock_call_later,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()) as mock_forward,
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coordinator.check_new_interval = MagicMock(return_value=True)
            mock_coordinator.has_confirmed_price = False
            mock_coordinator.is_rate_limited = False
            mock_coordinator.get_next_poll_delay = MagicMock(return_value=None)
            mock_coordinator.async_refresh = AsyncMock()
            mock_coordinator.update_from_websocket = MagicMock()
            mock_coordinator_class.return_value = mock_coordinator

            mock_ws = AsyncMock()
            mock_ws.start = AsyncMock()
            mock_ws_class.return_value = mock_ws

            mock_unsub = MagicMock()
            mock_track_time.return_value = mock_unsub
            mock_call_later.return_value = MagicMock()

            result = await async_setup_entry(hass, entry)

            assert result is True
            assert entry.runtime_data is not None
            assert "test_subentry_id" in entry.runtime_data.sites
            assert entry.runtime_data.sites["test_subentry_id"].coordinator == mock_coordinator
            assert entry.runtime_data.sites["test_subentry_id"].websocket_client == mock_ws

            mock_coordinator.async_config_entry_first_refresh.assert_called_once()
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
            patch("custom_components.amber_express.async_track_time_change") as mock_track_time,
            patch("custom_components.amber_express.async_call_later") as mock_call_later,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coordinator.has_confirmed_price = False
            mock_coordinator.is_rate_limited = False
            mock_coordinator.get_next_poll_delay = MagicMock(return_value=None)
            mock_coordinator_class.return_value = mock_coordinator

            mock_unsub = MagicMock()
            mock_track_time.return_value = mock_unsub
            mock_call_later.return_value = MagicMock()

            result = await async_setup_entry(hass, entry)

            assert result is True
            assert entry.runtime_data.sites["test_subentry_id"].websocket_client is None
            mock_ws_class.assert_not_called()

    async def test_setup_entry_interval_check(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test interval check polling is set up correctly with sub-second scheduling."""
        entry = create_mock_entry_with_subentry(hass)

        captured_callback: Any = None
        captured_seconds: Any = None

        def capture_track_time(hass: HomeAssistant, callback: Any, second: Any = None) -> MagicMock:
            nonlocal captured_callback, captured_seconds
            captured_callback = callback
            captured_seconds = second
            return MagicMock()

        with (
            patch("custom_components.amber_express.AmberDataCoordinator") as mock_coordinator_class,
            patch("custom_components.amber_express.AmberWebSocketClient") as mock_ws_class,
            patch(
                "custom_components.amber_express.async_track_time_change",
                side_effect=capture_track_time,
            ),
            patch("custom_components.amber_express.async_call_later") as mock_call_later,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coordinator.check_new_interval = MagicMock(return_value=True)
            mock_coordinator.has_confirmed_price = False
            mock_coordinator.is_rate_limited = False
            mock_coordinator.get_next_poll_delay = MagicMock(return_value=5.5)
            mock_coordinator.async_refresh = AsyncMock()
            mock_coordinator.update_from_websocket = MagicMock()
            mock_coordinator_class.return_value = mock_coordinator

            mock_ws = AsyncMock()
            mock_ws.start = AsyncMock()
            mock_ws_class.return_value = mock_ws

            mock_cancel = MagicMock()
            mock_call_later.return_value = mock_cancel

            await async_setup_entry(hass, entry)

            # Check interval detection seconds
            assert captured_seconds == INTERVAL_CHECK_SECONDS
            assert captured_callback is not None

            # Test the callback - check_new_interval returns True (new interval)
            mock_coordinator.async_refresh.reset_mock()
            mock_call_later.reset_mock()
            await captured_callback(None)

            # Should poll immediately for new interval
            mock_coordinator.async_refresh.assert_called_once()
            # Should schedule next poll with sub-second delay
            mock_call_later.assert_called()

    async def test_setup_entry_poll_skipped_when_not_new_interval(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test polling is skipped when check_new_interval returns False."""
        entry = create_mock_entry_with_subentry(hass)

        captured_callback: Any = None

        def capture_track_time(hass: HomeAssistant, callback: Any, second: Any = None) -> MagicMock:
            nonlocal captured_callback
            captured_callback = callback
            return MagicMock()

        with (
            patch("custom_components.amber_express.AmberDataCoordinator") as mock_coordinator_class,
            patch("custom_components.amber_express.AmberWebSocketClient") as mock_ws_class,
            patch(
                "custom_components.amber_express.async_track_time_change",
                side_effect=capture_track_time,
            ),
            patch("custom_components.amber_express.async_call_later") as mock_call_later,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coordinator.check_new_interval = MagicMock(return_value=False)
            mock_coordinator.has_confirmed_price = False
            mock_coordinator.is_rate_limited = False
            mock_coordinator.get_next_poll_delay = MagicMock(return_value=None)
            mock_coordinator.async_refresh = AsyncMock()
            mock_coordinator.update_from_websocket = MagicMock()
            mock_coordinator_class.return_value = mock_coordinator

            mock_ws = AsyncMock()
            mock_ws.start = AsyncMock()
            mock_ws_class.return_value = mock_ws

            mock_call_later.return_value = MagicMock()

            await async_setup_entry(hass, entry)

            # Test the callback - check_new_interval returns False, so refresh not called
            mock_coordinator.async_refresh.reset_mock()
            await captured_callback(None)
            mock_coordinator.async_refresh.assert_not_called()


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry."""

    async def test_unload_entry_success(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test successful unload."""
        entry = create_mock_entry_with_subentry(hass)

        mock_unsub = MagicMock()
        mock_ws = AsyncMock()
        mock_ws.stop = AsyncMock()

        # Set up runtime data as if setup succeeded
        from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData  # noqa: PLC0415

        mock_coordinator = MagicMock()
        entry.runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=mock_coordinator,
                    websocket_client=mock_ws,
                    unsub_time_change=mock_unsub,
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
            mock_unsub.assert_called_once()
            mock_ws.stop.assert_called_once()

    async def test_unload_entry_without_websocket(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test unload without websocket."""
        entry = create_mock_entry_with_subentry(hass)

        mock_unsub = MagicMock()

        from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData  # noqa: PLC0415

        mock_coordinator = MagicMock()
        entry.runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=mock_coordinator,
                    websocket_client=None,
                    unsub_time_change=mock_unsub,
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
            mock_unsub.assert_called_once()

    async def test_unload_entry_failure(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test failed unload preserves runtime data."""
        entry = create_mock_entry_with_subentry(hass)

        from custom_components.amber_express import AmberRuntimeData, SiteRuntimeData  # noqa: PLC0415

        mock_coordinator = MagicMock()
        runtime_data = AmberRuntimeData(
            sites={
                "test_subentry_id": SiteRuntimeData(
                    coordinator=mock_coordinator,
                    websocket_client=None,
                    unsub_time_change=None,
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


class TestIntervalCheckSeconds:
    """Tests for INTERVAL_CHECK_SECONDS constant."""

    def test_interval_check_seconds_contains_expected_values(self) -> None:
        """Test INTERVAL_CHECK_SECONDS contains expected values for detecting intervals."""
        assert 0 in INTERVAL_CHECK_SECONDS
        assert 5 in INTERVAL_CHECK_SECONDS
        assert all(0 <= s < 60 for s in INTERVAL_CHECK_SECONDS)
