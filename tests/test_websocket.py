"""Tests for the WebSocket client."""

# pyright: reportArgumentType=false
# pyright: reportOptionalSubscript=false
# pyright: reportMissingImports=false

import asyncio
from datetime import UTC, datetime
import json
from types import TracebackType
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from amberelectric.models import AdvancedPrice, TariffInformation
from homeassistant.core import HomeAssistant
import pytest

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory

from custom_components.amber_express.const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DESCRIPTOR,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_NEM_TIME,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_SPOT_PER_KWH,
    ATTR_START_TIME,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    WS_MAX_RECONNECT_DELAY,
    WS_MIN_RECONNECT_DELAY,
)
from custom_components.amber_express.websocket import WS_CHANNEL_TYPE_MAP, AmberWebSocketClient
from tests.conftest import make_current_interval

# Suppress unawaited coroutine warnings in tests
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


def make_ws_price_interval(
    *,
    channel_type: str = "general",
    per_kwh: float = 25.0,
    spot_per_kwh: float = 20.0,
    renewables: float = 45.0,
    estimate: bool = False,
    descriptor: str = "neutral",
    spike_status: str = "none",
) -> dict:
    """Create valid WebSocket price interval data matching SDK CurrentInterval format."""
    return {
        "type": "CurrentInterval",
        "date": "2024-01-01",
        "duration": 5,
        "startTime": "2024-01-01T10:00:00Z",
        "endTime": "2024-01-01T10:05:00Z",
        "nemTime": "2024-01-01T21:00:00+11:00",
        "perKwh": per_kwh,
        "spotPerKwh": spot_per_kwh,
        "renewables": renewables,
        "channelType": channel_type,
        "spikeStatus": spike_status,
        "descriptor": descriptor,
        "estimate": estimate,
    }


class TestWSChannelTypeMap:
    """Tests for WS_CHANNEL_TYPE_MAP constant."""

    def test_channel_type_mapping(self) -> None:
        """Test channel type mapping."""
        assert WS_CHANNEL_TYPE_MAP["general"] == CHANNEL_GENERAL
        assert WS_CHANNEL_TYPE_MAP["feedIn"] == CHANNEL_FEED_IN
        assert WS_CHANNEL_TYPE_MAP["controlledLoad"] == CHANNEL_CONTROLLED_LOAD


class TestAmberWebSocketClient:
    """Tests for AmberWebSocketClient."""

    @pytest.fixture
    def mock_on_message(self) -> MagicMock:
        """Return a mock on_message callback."""
        return MagicMock()

    @pytest.fixture
    def ws_client(self, hass: HomeAssistant, mock_on_message: MagicMock) -> AmberWebSocketClient:
        """Create a websocket client for testing."""
        return AmberWebSocketClient(
            hass=hass,
            api_token="test_token",  # noqa: S106
            site_id="test_site",
            on_message=mock_on_message,
        )

    def test_client_init(self, ws_client: AmberWebSocketClient) -> None:
        """Test client initialization."""
        assert ws_client.api_token == "test_token"  # noqa: S105
        assert ws_client.site_id == "test_site"
        assert ws_client._running is False
        assert ws_client._connected is False
        assert ws_client._reconnect_delay == WS_MIN_RECONNECT_DELAY

    def test_connected_property(self, ws_client: AmberWebSocketClient) -> None:
        """Test connected property."""
        assert ws_client.connected is False
        ws_client._connected = True
        assert ws_client.connected is True

    async def test_start(self, hass: HomeAssistant, mock_on_message: MagicMock) -> None:
        """Test start method."""
        client = AmberWebSocketClient(
            hass=hass,
            api_token="test_token",  # noqa: S106
            site_id="test_site",
            on_message=mock_on_message,
        )

        # Create a real task that finishes immediately
        async def noop() -> None:
            pass

        task = asyncio.create_task(noop())
        await task  # Let it complete

        with patch.object(client.hass, "async_create_background_task", return_value=task) as mock_create_task:
            await client.start()

            assert client._running is True
            mock_create_task.assert_called_once()
            assert client._task == task

    async def test_start_already_running(self, hass: HomeAssistant, mock_on_message: MagicMock) -> None:
        """Test start when already running does nothing."""
        client = AmberWebSocketClient(
            hass=hass,
            api_token="test_token",  # noqa: S106
            site_id="test_site",
            on_message=mock_on_message,
        )
        client._running = True

        with patch.object(client.hass, "async_create_background_task") as mock_create_task:
            await client.start()

            mock_create_task.assert_not_called()

    async def test_stop(self, hass: HomeAssistant, mock_on_message: MagicMock) -> None:
        """Test stop method."""
        client = AmberWebSocketClient(
            hass=hass,
            api_token="test_token",  # noqa: S106
            site_id="test_site",
            on_message=mock_on_message,
        )
        client._running = True
        client._connected = True

        # Create a proper mock for the websocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.close = AsyncMock()
        client._ws = mock_ws

        # Create a real asyncio task that we can await and cancel
        async def dummy_coro() -> None:
            await asyncio.sleep(10)

        client._task = asyncio.create_task(dummy_coro())

        await client.stop()

        assert client._running is False
        assert client._connected is False
        mock_ws.close.assert_called_once()
        assert client._task is None

    async def test_stop_already_stopped(self, ws_client: AmberWebSocketClient) -> None:
        """Test stop when already stopped."""
        ws_client._running = False
        ws_client._ws = None
        ws_client._task = None

        await ws_client.stop()

        assert ws_client._connected is False

    async def test_run_cancelled(self, ws_client: AmberWebSocketClient) -> None:
        """Test _run handles CancelledError."""
        ws_client._running = True

        with patch.object(ws_client, "_connect_and_listen", new=AsyncMock(side_effect=asyncio.CancelledError)):
            await ws_client._run()

        # Should have broken out of loop
        assert ws_client._running is True

    async def test_run_auth_failure_stops(self, ws_client: AmberWebSocketClient) -> None:
        """Test _run stops on 403 auth failure."""
        ws_client._running = True

        error = aiohttp.WSServerHandshakeError(
            request_info=MagicMock(),
            history=(),
            status=403,
            message="Forbidden",
            headers=MagicMock(),
        )

        with patch.object(ws_client, "_connect_and_listen", new=AsyncMock(side_effect=error)):
            await ws_client._run()

        assert ws_client._running is False

    async def test_run_other_handshake_error_reconnects(self, ws_client: AmberWebSocketClient) -> None:
        """Test _run reconnects on non-403 handshake error."""
        ws_client._running = True
        call_count = 0

        error = aiohttp.WSServerHandshakeError(
            request_info=MagicMock(),
            history=(),
            status=500,
            message="Server Error",
            headers=MagicMock(),
        )

        async def side_effect() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise error
            ws_client._running = False

        with (
            patch.object(ws_client, "_connect_and_listen", side_effect=side_effect),
            patch("custom_components.amber_express.websocket.asyncio.sleep", new=AsyncMock()),
        ):
            await ws_client._run()

        assert call_count == 2
        assert ws_client._reconnect_delay == WS_MIN_RECONNECT_DELAY * 2

    async def test_run_generic_error_reconnects(self, ws_client: AmberWebSocketClient) -> None:
        """Test _run reconnects on generic error."""
        ws_client._running = True
        call_count = 0

        async def side_effect() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "Generic error"
                raise RuntimeError(msg)
            ws_client._running = False

        with (
            patch.object(ws_client, "_connect_and_listen", side_effect=side_effect),
            patch("custom_components.amber_express.websocket.asyncio.sleep", new=AsyncMock()),
        ):
            await ws_client._run()

        assert call_count == 2

    async def test_run_exponential_backoff_max(self, ws_client: AmberWebSocketClient) -> None:
        """Test _run respects max reconnect delay."""
        ws_client._running = True
        ws_client._reconnect_delay = WS_MAX_RECONNECT_DELAY
        call_count = 0

        async def side_effect() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "Error"
                raise RuntimeError(msg)
            ws_client._running = False

        with (
            patch.object(ws_client, "_connect_and_listen", side_effect=side_effect),
            patch("custom_components.amber_express.websocket.asyncio.sleep", new=AsyncMock()),
        ):
            await ws_client._run()

        assert ws_client._reconnect_delay == WS_MAX_RECONNECT_DELAY

    async def test_handle_message_valid_json(self, ws_client: AmberWebSocketClient, mock_on_message: MagicMock) -> None:  # noqa: ARG002
        """Test _handle_message with valid JSON."""
        message = '{"service": "live-prices", "action": "price-update", "data": {"prices": []}}'

        await ws_client._handle_message(message)

    async def test_handle_message_invalid_json(self, ws_client: AmberWebSocketClient) -> None:
        """Test _handle_message with invalid JSON."""
        message = "not valid json"

        await ws_client._handle_message(message)

    async def test_handle_message_subscribe_success(self, ws_client: AmberWebSocketClient) -> None:
        """Test _handle_message with successful subscription."""
        message = '{"service": "live-prices", "action": "subscribe", "status": 200}'

        await ws_client._handle_message(message)

    async def test_handle_message_subscribe_failure(self, ws_client: AmberWebSocketClient) -> None:
        """Test _handle_message with failed subscription."""
        message = '{"service": "live-prices", "action": "subscribe", "status": 400}'

        await ws_client._handle_message(message)

    async def test_handle_message_price_update(
        self, ws_client: AmberWebSocketClient, mock_on_message: MagicMock
    ) -> None:
        """Test _handle_message with price update."""
        price_data = make_ws_price_interval(
            channel_type="general",
            per_kwh=25.0,
            spot_per_kwh=20.0,
            descriptor="neutral",
            spike_status="none",
            renewables=45.5,
            estimate=False,
        )
        message = json.dumps(
            {
                "service": "live-prices",
                "action": "price-update",
                "data": {
                    "siteId": "test",
                    "prices": [price_data],
                },
            }
        )

        await ws_client._handle_message(message)

        mock_on_message.assert_called_once()
        call_args = mock_on_message.call_args[0][0]
        assert CHANNEL_GENERAL in call_args
        assert call_args[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25

    async def test_handle_message_price_update_empty(
        self, ws_client: AmberWebSocketClient, mock_on_message: MagicMock
    ) -> None:
        """Test _handle_message with empty price update."""
        message = '{"service": "live-prices", "action": "price-update", "data": {}}'

        await ws_client._handle_message(message)

        mock_on_message.assert_not_called()

    async def test_handle_message_other_action(self, ws_client: AmberWebSocketClient) -> None:
        """Test _handle_message with other action."""
        message = '{"service": "other-service", "action": "other-action", "status": 200}'

        await ws_client._handle_message(message)

    def test_process_price_update_empty_data(self, ws_client: AmberWebSocketClient) -> None:
        """Test _process_price_update with empty data."""
        result = ws_client._process_price_update({})
        assert result is None

    def test_process_price_update_with_prices(self, ws_client: AmberWebSocketClient) -> None:
        """Test _process_price_update with price data."""
        data = {
            "siteId": "test",
            "prices": [
                make_ws_price_interval(
                    channel_type="general",
                    per_kwh=25.0,
                    spot_per_kwh=20.0,
                    descriptor="neutral",
                    spike_status="none",
                    renewables=45.5,
                    estimate=False,
                )
            ],
        }

        result = ws_client._process_price_update(data)

        assert result is not None
        assert CHANNEL_GENERAL in result
        assert result[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25
        assert result[CHANNEL_GENERAL][ATTR_SPOT_PER_KWH] == 0.20
        assert result[CHANNEL_GENERAL][ATTR_DESCRIPTOR] == "neutral"
        assert result[CHANNEL_GENERAL][ATTR_SPIKE_STATUS] == "none"
        assert result[CHANNEL_GENERAL][ATTR_RENEWABLES] == 45.5
        assert result[CHANNEL_GENERAL][ATTR_ESTIMATE] is False

    def test_process_price_update_feed_in(self, ws_client: AmberWebSocketClient) -> None:
        """Test _process_price_update with feed-in channel."""
        data = {
            "siteId": "test",
            "prices": [make_ws_price_interval(channel_type="feedIn", per_kwh=10.0)],
        }

        result = ws_client._process_price_update(data)

        assert result is not None
        assert CHANNEL_FEED_IN in result
        assert result[CHANNEL_FEED_IN][ATTR_PER_KWH] == 0.10

    def test_process_price_update_unknown_channel(self, ws_client: AmberWebSocketClient) -> None:
        """Test _process_price_update with unknown channel type fails to parse."""
        # SDK's ChannelType enum only accepts valid values, so unknown fails
        data = {
            "siteId": "test",
            "prices": [make_ws_price_interval(channel_type="unknown")],
        }

        result = ws_client._process_price_update(data)

        # Unknown channel types fail SDK parsing, so result is None
        assert result is None

    def test_process_price_update_no_channel_type(self, ws_client: AmberWebSocketClient) -> None:
        """Test _process_price_update with missing channel type fails validation."""
        data = {
            "prices": [
                {
                    "perKwh": 25.0,
                }
            ]
        }

        result = ws_client._process_price_update(data)

        assert result is None

    def test_extract_channel_data_minimal(self, ws_client: AmberWebSocketClient) -> None:
        """Test _extract_channel_data with minimal CurrentInterval."""
        interval = make_current_interval(per_kwh=25.0)
        result = ws_client._extract_channel_data(interval)
        assert result is not None
        assert result[ATTR_PER_KWH] == 0.25

    def test_extract_channel_data_full(self, ws_client: AmberWebSocketClient) -> None:
        """Test _extract_channel_data with full data."""
        interval = make_current_interval(
            per_kwh=25.0,
            spot_per_kwh=20.0,
            renewables=45.5,
            estimate=False,
        )

        result = ws_client._extract_channel_data(interval)

        assert result[ATTR_PER_KWH] == 0.25
        assert result[ATTR_SPOT_PER_KWH] == 0.20
        assert result[ATTR_DESCRIPTOR] == "neutral"
        assert result[ATTR_SPIKE_STATUS] == "none"
        # CurrentInterval uses datetime objects, so start_time is ISO formatted
        assert ATTR_START_TIME in result
        assert ATTR_END_TIME in result
        assert ATTR_NEM_TIME in result
        assert result[ATTR_RENEWABLES] == 45.5
        assert result[ATTR_ESTIMATE] is False

    def test_extract_channel_data_with_advanced_price(self, ws_client: AmberWebSocketClient) -> None:
        """Test _extract_channel_data with advanced price."""
        advanced = AdvancedPrice(low=20.0, predicted=25.0, high=30.0)
        interval = make_current_interval(per_kwh=25.0, advanced_price=advanced)

        result = ws_client._extract_channel_data(interval)

        assert result[ATTR_PER_KWH] == 0.25
        assert result[ATTR_ADVANCED_PRICE]["low"] == 0.20
        assert result[ATTR_ADVANCED_PRICE]["predicted"] == 0.25
        assert result[ATTR_ADVANCED_PRICE]["high"] == 0.30

    def test_extract_channel_data_no_advanced_price(self, ws_client: AmberWebSocketClient) -> None:
        """Test _extract_channel_data without advanced price."""
        interval = make_current_interval(per_kwh=25.0)

        result = ws_client._extract_channel_data(interval)

        assert result[ATTR_PER_KWH] == 0.25
        assert ATTR_ADVANCED_PRICE not in result

    def test_extract_channel_data_with_tariff_info(self, ws_client: AmberWebSocketClient) -> None:
        """Test _extract_channel_data with tariff information."""
        tariff = TariffInformation(period="peak", season="summer", demand_window=True)
        interval = make_current_interval(per_kwh=15.0)
        # SDK CurrentInterval has tariff_information as optional field
        interval.tariff_information = tariff

        result = ws_client._extract_channel_data(interval)

        assert result[ATTR_PER_KWH] == 0.15
        assert result[ATTR_DEMAND_WINDOW] is True
        assert result[ATTR_TARIFF_PERIOD] == "peak"
        assert result[ATTR_TARIFF_SEASON] == "summer"

    def test_is_stale_no_last_update(self, ws_client: AmberWebSocketClient) -> None:
        """Test _is_stale returns False when no last update."""
        ws_client._last_price_update = None
        assert ws_client._is_stale() is False

    def test_is_stale_recent_update(self, ws_client: AmberWebSocketClient, freezer: "FrozenDateTimeFactory") -> None:
        """Test _is_stale returns False for recent update."""
        freezer.move_to("2024-01-01 12:00:00")
        ws_client._last_price_update = datetime.now(UTC)

        # Move forward 5 minutes (less than 6 minute threshold)
        freezer.move_to("2024-01-01 12:05:00")
        assert ws_client._is_stale() is False

    def test_is_stale_old_update(self, ws_client: AmberWebSocketClient, freezer: "FrozenDateTimeFactory") -> None:
        """Test _is_stale returns True for old update."""
        freezer.move_to("2024-01-01 12:00:00")
        ws_client._last_price_update = datetime.now(UTC)

        # Move forward 7 minutes (more than 6 minute threshold)
        freezer.move_to("2024-01-01 12:07:00")
        assert ws_client._is_stale() is True

    async def test_connect_and_listen_text_message(self, hass: HomeAssistant, mock_on_message: MagicMock) -> None:
        """Test _connect_and_listen handles text messages."""
        client = AmberWebSocketClient(
            hass=hass,
            api_token="test_token",  # noqa: S106
            site_id="test_site",
            on_message=mock_on_message,
        )

        # Create mock messages
        text_msg = MagicMock()
        text_msg.type = aiohttp.WSMsgType.TEXT
        text_msg.data = '{"service": "live-prices", "action": "subscribe", "status": 200}'

        close_msg = MagicMock()
        close_msg.type = aiohttp.WSMsgType.CLOSED

        # Create mock websocket with async iterator
        mock_ws = AsyncIterableMock([text_msg, close_msg])
        mock_ws.send_json = AsyncMock()

        mock_session = MagicMock()
        mock_session.ws_connect = MagicMock(return_value=AsyncContextManagerMock(mock_ws))

        with patch(
            "custom_components.amber_express.websocket.async_get_clientsession",
            return_value=mock_session,
        ):
            await client._connect_and_listen()

            assert client._connected is True
            mock_ws.send_json.assert_called_once()

    async def test_connect_and_listen_error_message(self, hass: HomeAssistant, mock_on_message: MagicMock) -> None:
        """Test _connect_and_listen handles error messages."""
        client = AmberWebSocketClient(
            hass=hass,
            api_token="test_token",  # noqa: S106
            site_id="test_site",
            on_message=mock_on_message,
        )

        # Create mock error message
        error_msg = MagicMock()
        error_msg.type = aiohttp.WSMsgType.ERROR

        # Create mock websocket with async iterator
        mock_ws = AsyncIterableMock([error_msg])
        mock_ws.send_json = AsyncMock()
        mock_ws.exception = MagicMock(return_value=Exception("WS Error"))

        mock_session = MagicMock()
        mock_session.ws_connect = MagicMock(return_value=AsyncContextManagerMock(mock_ws))

        with patch(
            "custom_components.amber_express.websocket.async_get_clientsession",
            return_value=mock_session,
        ):
            await client._connect_and_listen()

            assert client._connected is True

    async def test_connect_and_listen_closing_message(self, hass: HomeAssistant, mock_on_message: MagicMock) -> None:
        """Test _connect_and_listen handles closing messages."""
        client = AmberWebSocketClient(
            hass=hass,
            api_token="test_token",  # noqa: S106
            site_id="test_site",
            on_message=mock_on_message,
        )

        # Create mock closing message
        closing_msg = MagicMock()
        closing_msg.type = aiohttp.WSMsgType.CLOSING

        # Create mock websocket with async iterator
        mock_ws = AsyncIterableMock([closing_msg])
        mock_ws.send_json = AsyncMock()

        mock_session = MagicMock()
        mock_session.ws_connect = MagicMock(return_value=AsyncContextManagerMock(mock_ws))

        with patch(
            "custom_components.amber_express.websocket.async_get_clientsession",
            return_value=mock_session,
        ):
            await client._connect_and_listen()

            assert client._connected is True


class AsyncIterableMock:
    """Mock for async iterable websocket with receive() support."""

    def __init__(self, messages: list[Any]) -> None:
        """Initialize with messages to iterate."""
        self.messages = messages
        self.index = 0

    def __aiter__(self) -> "AsyncIterableMock":
        """Return async iterator."""
        return self

    async def __anext__(self) -> Any:
        """Get next message."""
        if self.index < len(self.messages):
            msg = self.messages[self.index]
            self.index += 1
            return msg
        raise StopAsyncIteration

    async def receive(self) -> Any:
        """Simulate ws.receive() - returns next message or raises StopAsyncIteration."""
        if self.index < len(self.messages):
            msg = self.messages[self.index]
            self.index += 1
            return msg
        raise StopAsyncIteration


class AsyncContextManagerMock:
    """Mock for async context manager."""

    def __init__(self, return_value: Any) -> None:
        """Initialize with return value."""
        self.return_value = return_value

    async def __aenter__(self) -> Any:
        """Enter async context."""
        return self.return_value

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context."""
        return
