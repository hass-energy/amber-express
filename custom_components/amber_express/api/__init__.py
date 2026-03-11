"""API package for Amber Electric HTTP and WebSocket clients."""

from .client import AmberApiClient, AmberApiError, RateLimitedError
from .rate_limiter import ExponentialBackoffRateLimiter
from .websocket import WS_CHANNEL_TYPE_MAP, AmberWebSocketClient

__all__ = [
    "WS_CHANNEL_TYPE_MAP",
    "AmberApiClient",
    "AmberApiError",
    "AmberWebSocketClient",
    "ExponentialBackoffRateLimiter",
    "RateLimitedError",
]
