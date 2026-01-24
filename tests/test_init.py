"""Tests for integration setup and unload."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amber_express import (
    POLL_SECONDS,
    async_options_update_listener,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.amber_express.const import (
    CONF_API_TOKEN,
    CONF_ENABLE_WEBSOCKET,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DOMAIN,
)


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    async def test_setup_entry_success(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test successful setup."""
        mock_config_entry.add_to_hass(hass)

        with (
            patch(
                "custom_components.amber_express.AmberDataCoordinator"
            ) as mock_coordinator_class,
            patch(
                "custom_components.amber_express.AmberWebSocketClient"
            ) as mock_ws_class,
            patch(
                "custom_components.amber_express.async_track_time_change"
            ) as mock_track_time,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()) as mock_forward,
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coordinator.should_poll = MagicMock(return_value=True)
            mock_coordinator.async_refresh = AsyncMock()
            mock_coordinator.update_from_websocket = MagicMock()
            mock_coordinator_class.return_value = mock_coordinator

            mock_ws = AsyncMock()
            mock_ws.start = AsyncMock()
            mock_ws_class.return_value = mock_ws

            mock_unsub = MagicMock()
            mock_track_time.return_value = mock_unsub

            result = await async_setup_entry(hass, mock_config_entry)

            assert result is True
            assert DOMAIN in hass.data
            assert mock_config_entry.entry_id in hass.data[DOMAIN]
            assert hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"] == mock_coordinator
            assert hass.data[DOMAIN][mock_config_entry.entry_id]["websocket_client"] == mock_ws

            mock_coordinator.async_config_entry_first_refresh.assert_called_once()
            mock_ws.start.assert_called_once()
            mock_forward.assert_called_once()

    async def test_setup_entry_without_websocket(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test setup without websocket enabled."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test Site",
            data={
                CONF_API_TOKEN: "test_token",
                CONF_SITE_ID: "test_site",
                CONF_SITE_NAME: "Test",
            },
            options={CONF_ENABLE_WEBSOCKET: False},
        )
        entry.add_to_hass(hass)

        with (
            patch(
                "custom_components.amber_express.AmberDataCoordinator"
            ) as mock_coordinator_class,
            patch(
                "custom_components.amber_express.AmberWebSocketClient"
            ) as mock_ws_class,
            patch("custom_components.amber_express.async_track_time_change") as mock_track_time,
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coordinator_class.return_value = mock_coordinator

            mock_unsub = MagicMock()
            mock_track_time.return_value = mock_unsub

            result = await async_setup_entry(hass, entry)

            assert result is True
            assert hass.data[DOMAIN][entry.entry_id]["websocket_client"] is None
            mock_ws_class.assert_not_called()

    async def test_setup_entry_clock_aligned_poll(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test clock-aligned polling is set up correctly."""
        mock_config_entry.add_to_hass(hass)

        captured_callback = None
        captured_seconds = None

        def capture_track_time(hass, callback, second=None):
            nonlocal captured_callback, captured_seconds
            captured_callback = callback
            captured_seconds = second
            return MagicMock()

        with (
            patch(
                "custom_components.amber_express.AmberDataCoordinator"
            ) as mock_coordinator_class,
            patch("custom_components.amber_express.AmberWebSocketClient") as mock_ws_class,
            patch(
                "custom_components.amber_express.async_track_time_change",
                side_effect=capture_track_time,
            ),
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coordinator.should_poll = MagicMock(return_value=True)
            mock_coordinator.async_refresh = AsyncMock()
            mock_coordinator.update_from_websocket = MagicMock()
            mock_coordinator_class.return_value = mock_coordinator

            mock_ws = AsyncMock()
            mock_ws.start = AsyncMock()
            mock_ws_class.return_value = mock_ws

            await async_setup_entry(hass, mock_config_entry)

            assert captured_seconds == POLL_SECONDS
            assert captured_callback is not None

            # Test the callback - should_poll returns True
            await captured_callback(None)
            mock_coordinator.async_refresh.assert_called_once()

    async def test_setup_entry_poll_skipped_when_not_needed(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test polling is skipped when should_poll returns False."""
        mock_config_entry.add_to_hass(hass)

        captured_callback = None

        def capture_track_time(hass, callback, second=None):
            nonlocal captured_callback
            captured_callback = callback
            return MagicMock()

        with (
            patch(
                "custom_components.amber_express.AmberDataCoordinator"
            ) as mock_coordinator_class,
            patch("custom_components.amber_express.AmberWebSocketClient") as mock_ws_class,
            patch(
                "custom_components.amber_express.async_track_time_change",
                side_effect=capture_track_time,
            ),
            patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
        ):
            mock_coordinator = AsyncMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coordinator.should_poll = MagicMock(return_value=False)
            mock_coordinator.async_refresh = AsyncMock()
            mock_coordinator.update_from_websocket = MagicMock()
            mock_coordinator_class.return_value = mock_coordinator

            mock_ws = AsyncMock()
            mock_ws.start = AsyncMock()
            mock_ws_class.return_value = mock_ws

            await async_setup_entry(hass, mock_config_entry)

            # Test the callback - should_poll returns False, so refresh not called
            mock_coordinator.async_refresh.reset_mock()
            await captured_callback(None)
            mock_coordinator.async_refresh.assert_not_called()


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry."""

    async def test_unload_entry_success(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test successful unload."""
        mock_config_entry.add_to_hass(hass)

        mock_unsub = MagicMock()
        mock_ws = AsyncMock()
        mock_ws.stop = AsyncMock()

        hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "coordinator": MagicMock(),
                "websocket_client": mock_ws,
                "unsub_time_change": mock_unsub,
            }
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            result = await async_unload_entry(hass, mock_config_entry)

            assert result is True
            assert mock_config_entry.entry_id not in hass.data[DOMAIN]
            mock_unsub.assert_called_once()
            mock_ws.stop.assert_called_once()

    async def test_unload_entry_without_websocket(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test unload without websocket."""
        mock_config_entry.add_to_hass(hass)

        mock_unsub = MagicMock()

        hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "coordinator": MagicMock(),
                "websocket_client": None,
                "unsub_time_change": mock_unsub,
            }
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            result = await async_unload_entry(hass, mock_config_entry)

            assert result is True
            mock_unsub.assert_called_once()

    async def test_unload_entry_without_unsub(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test unload without time change unsubscribe."""
        mock_config_entry.add_to_hass(hass)

        hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "coordinator": MagicMock(),
                "websocket_client": None,
                "unsub_time_change": None,
            }
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            result = await async_unload_entry(hass, mock_config_entry)

            assert result is True

    async def test_unload_entry_failure(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test failed unload."""
        mock_config_entry.add_to_hass(hass)

        hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "coordinator": MagicMock(),
                "websocket_client": None,
                "unsub_time_change": None,
            }
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=False),
        ):
            result = await async_unload_entry(hass, mock_config_entry)

            assert result is False
            # Entry should still be in data since unload failed
            assert mock_config_entry.entry_id in hass.data[DOMAIN]


class TestAsyncOptionsUpdateListener:
    """Tests for async_options_update_listener."""

    async def test_options_update_reloads_entry(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test options update triggers reload."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new=AsyncMock(),
        ) as mock_reload:
            await async_options_update_listener(hass, mock_config_entry)

            mock_reload.assert_called_once_with(mock_config_entry.entry_id)


class TestPollSeconds:
    """Tests for POLL_SECONDS constant."""

    def test_poll_seconds_contains_expected_values(self) -> None:
        """Test POLL_SECONDS contains expected values."""
        assert 0 in POLL_SECONDS
        assert 5 in POLL_SECONDS
        assert all(0 <= s < 60 for s in POLL_SECONDS)
