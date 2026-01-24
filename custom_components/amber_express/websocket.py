"""WebSocket client for Amber Express integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from datetime import UTC, datetime, timedelta
import json
import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
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
    WEBSOCKET_URL,
    WS_HEARTBEAT_INTERVAL,
    WS_MAX_RECONNECT_DELAY,
    WS_MIN_RECONNECT_DELAY,
    WS_STALE_TIMEOUT,
)
from .types import AdvancedPriceData, ChannelData, WSPriceInterval, is_ws_price_update

_LOGGER = logging.getLogger(__name__)

# Map Amber WebSocket channel types to our constants
WS_CHANNEL_TYPE_MAP = {
    "general": CHANNEL_GENERAL,
    "feedIn": CHANNEL_FEED_IN,
    "controlledLoad": CHANNEL_CONTROLLED_LOAD,
}


class AmberWebSocketClient:
    """WebSocket client for Amber Express prices."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_token: str,
        site_id: str,
        on_message: Callable[[dict[str, ChannelData]], None],
    ) -> None:
        """Initialize the WebSocket client."""
        self.hass = hass
        self.api_token = api_token
        self.site_id = site_id
        self.on_message = on_message

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False
        self._reconnect_delay = WS_MIN_RECONNECT_DELAY
        self._task: asyncio.Task | None = None
        self._connected = False
        self._last_price_update: datetime | None = None

    @property
    def connected(self) -> bool:
        """Return True if connected to WebSocket."""
        return self._connected

    async def start(self) -> None:
        """Start the WebSocket client."""
        if self._running:
            return

        self._running = True
        self._task = self.hass.async_create_background_task(
            self._run(),
            "amber_websocket_client",
        )
        _LOGGER.debug("WebSocket client started")

    async def stop(self) -> None:
        """Stop the WebSocket client."""
        self._running = False

        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

        # Note: We don't close the session as we use HA's shared client session

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        self._connected = False
        _LOGGER.debug("WebSocket client stopped")

    async def _run(self) -> None:
        """Run the WebSocket loop with reconnection."""
        auth_failed = False
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except aiohttp.WSServerHandshakeError as err:
                if err.status == 403:  # noqa: PLR2004
                    if not auth_failed:
                        _LOGGER.warning(
                            "WebSocket authentication failed (403). The Amber WebSocket API "
                            "is in alpha and may not be available for all accounts. "
                            "Disabling WebSocket updates - will use polling only."
                        )
                        auth_failed = True
                    # Stop trying to reconnect on auth failure
                    self._running = False
                    break
                _LOGGER.warning(
                    "WebSocket handshake error: %s. Reconnecting in %ds...",
                    err,
                    self._reconnect_delay,
                )
            except Exception as err:
                _LOGGER.warning(
                    "WebSocket connection error: %s. Reconnecting in %ds...",
                    err,
                    self._reconnect_delay,
                )

            self._connected = False

            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                # Exponential backoff
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    WS_MAX_RECONNECT_DELAY,
                )

    async def _connect_and_listen(self) -> None:
        """Connect to WebSocket and listen for messages."""
        # Use Home Assistant's shared client session (same as AmberWebSocket integration)
        session = async_get_clientsession(self.hass)

        # Use lowercase 'authorization' header as per AmberWebSocket implementation
        # Don't include Origin header - wscat works without it
        headers = {
            "authorization": f"Bearer {self.api_token}",
        }

        _LOGGER.debug("Connecting to Amber WebSocket at %s...", WEBSOCKET_URL)

        async with session.ws_connect(
            WEBSOCKET_URL,
            headers=headers,
            heartbeat=WS_HEARTBEAT_INTERVAL,
        ) as ws:
            self._ws = ws
            self._connected = True
            self._reconnect_delay = WS_MIN_RECONNECT_DELAY  # Reset on successful connect
            self._last_price_update = datetime.now(UTC)  # Initialize on connect
            _LOGGER.info("Connected to Amber WebSocket")

            # Subscribe to live prices
            subscribe_msg = {
                "service": "live-prices",
                "action": "subscribe",
                "data": {"siteId": self.site_id},
            }
            await ws.send_json(subscribe_msg)
            _LOGGER.debug("Sent subscribe message for site %s: %s", self.site_id, subscribe_msg)

            # Listen for messages with staleness detection
            while True:
                try:
                    # Use 60s receive timeout to periodically check staleness
                    msg = await asyncio.wait_for(ws.receive(), timeout=60)
                except TimeoutError:
                    # Check if connection is stale (no price updates for too long)
                    if self._is_stale():
                        _LOGGER.debug(
                            "No price updates received for %d seconds, reconnecting websocket...",
                            WS_STALE_TIMEOUT,
                        )
                        break
                    continue

                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", ws.exception())
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    _LOGGER.debug("WebSocket connection closed")
                    break

    def _is_stale(self) -> bool:
        """Check if the connection is stale (no price updates for too long)."""
        if self._last_price_update is None:
            return False
        elapsed = datetime.now(UTC) - self._last_price_update
        return elapsed > timedelta(seconds=WS_STALE_TIMEOUT)

    async def _handle_message(self, data: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            _LOGGER.warning("Received invalid JSON from WebSocket: %s", data[:100])
            return

        service = payload.get("service", "unknown")
        action = payload.get("action", "unknown")
        status = payload.get("status")

        # Log subscription response
        if action == "subscribe":
            if status == 200:  # noqa: PLR2004
                _LOGGER.info("WebSocket subscription successful: %s", payload)
            else:
                _LOGGER.warning("WebSocket subscription failed: %s", payload)
            return

        # Check for price update message
        if service == "live-prices" and action == "price-update":
            raw_data = payload.get("data", {})
            _LOGGER.debug("WebSocket raw message: %s", raw_data)

            processed_data = self._process_price_update(raw_data)
            if processed_data:
                # Update staleness tracker
                self._last_price_update = datetime.now(UTC)
                # Log will happen in coordinator.update_from_websocket via _log_price_data
                self.on_message(processed_data)
            else:
                _LOGGER.debug("WebSocket price-update: no data to process")
        else:
            _LOGGER.debug(
                "WebSocket message: service=%s, action=%s, status=%s",
                service,
                action,
                status,
            )

    def _process_price_update(self, data: object) -> dict[str, ChannelData] | None:
        """Process a price update message from the WebSocket."""
        if not is_ws_price_update(data):
            _LOGGER.debug("WebSocket message failed validation")
            return None

        result: dict[str, ChannelData] = {}

        for price_interval in data["prices"]:
            channel_type_raw = price_interval.get("channelType", "")
            if not channel_type_raw:
                continue
            channel = WS_CHANNEL_TYPE_MAP.get(channel_type_raw, channel_type_raw)

            processed = self._extract_channel_data(price_interval)
            if processed:
                result[channel] = processed

        return result if result else None

    def _extract_channel_data(self, interval: WSPriceInterval) -> ChannelData | None:
        """Extract data from a price interval in the WebSocket message."""
        # Get price data (API returns cents, convert to dollars)
        per_kwh_cents = interval.get("perKwh")
        spot_per_kwh_cents = interval.get("spotPerKwh")

        # Convert cents to dollars
        per_kwh = per_kwh_cents / 100 if per_kwh_cents is not None else None
        spot_per_kwh = spot_per_kwh_cents / 100 if spot_per_kwh_cents is not None else None

        result: ChannelData = {
            ATTR_PER_KWH: per_kwh,
            ATTR_SPOT_PER_KWH: spot_per_kwh,
            ATTR_START_TIME: interval.get("startTime"),
            ATTR_END_TIME: interval.get("endTime"),
            ATTR_NEM_TIME: interval.get("nemTime"),
            ATTR_RENEWABLES: interval.get("renewables"),
            ATTR_DESCRIPTOR: interval.get("descriptor"),
            ATTR_SPIKE_STATUS: interval.get("spikeStatus"),
            ATTR_ESTIMATE: interval.get("estimate"),
        }

        # Get advanced price if available (convert cents to dollars)
        advanced_price = interval.get("advancedPrice")
        if advanced_price:
            low_cents = advanced_price.get("low")
            predicted_cents = advanced_price.get("predicted")
            high_cents = advanced_price.get("high")
            advanced_price_data: AdvancedPriceData = {
                "low": low_cents / 100 if low_cents is not None else None,
                "predicted": predicted_cents / 100 if predicted_cents is not None else None,
                "high": high_cents / 100 if high_cents is not None else None,
            }
            result[ATTR_ADVANCED_PRICE] = advanced_price_data

        # Get tariff information if available
        tariff_info = interval.get("tariffInformation")
        if tariff_info:
            result[ATTR_DEMAND_WINDOW] = tariff_info.get("demandWindow")
            result[ATTR_TARIFF_PERIOD] = tariff_info.get("period")
            result[ATTR_TARIFF_SEASON] = tariff_info.get("season")

        return result
