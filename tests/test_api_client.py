"""Tests for the Amber API client."""

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

from amberelectric.rest import ApiException
from homeassistant.core import HomeAssistant
import pytest

from custom_components.amber_express.api_client import AmberApiClient, FetchResult
from custom_components.amber_express.rate_limiter import ExponentialBackoffRateLimiter


@pytest.fixture
def rate_limiter() -> ExponentialBackoffRateLimiter:
    """Create a rate limiter for testing."""
    return ExponentialBackoffRateLimiter()


@pytest.fixture
def api_client(hass: HomeAssistant, rate_limiter: ExponentialBackoffRateLimiter) -> AmberApiClient:
    """Create an API client for testing."""
    return AmberApiClient(hass, "test_token", rate_limiter)


class TestAmberApiClient:
    """Tests for AmberApiClient."""

    def test_init(self, api_client: AmberApiClient) -> None:
        """Test API client initialization."""
        assert api_client.last_status == HTTPStatus.OK
        assert api_client.rate_limit_info == {}

    async def test_fetch_sites_success(self, api_client: AmberApiClient) -> None:
        """Test successful site fetch."""
        mock_site = MagicMock()
        mock_site.id = "test_site"
        mock_response = MagicMock()
        mock_response.data = [mock_site]
        mock_response.headers = {}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await api_client.fetch_sites()

            assert result is not None
            assert len(result) == 1
            assert result[0].id == "test_site"
            assert api_client.last_status == HTTPStatus.OK

    async def test_fetch_sites_empty(self, api_client: AmberApiClient) -> None:
        """Test site fetch with no data."""
        mock_response = MagicMock()
        mock_response.data = None
        mock_response.headers = {}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await api_client.fetch_sites()

            assert result == []

    async def test_fetch_sites_api_exception(self, api_client: AmberApiClient) -> None:
        """Test site fetch with API exception."""
        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=ApiException(status=500)),
        ):
            result = await api_client.fetch_sites()

            assert result is None
            assert api_client.last_status == 500

    async def test_fetch_sites_rate_limited(
        self, api_client: AmberApiClient, rate_limiter: ExponentialBackoffRateLimiter
    ) -> None:
        """Test site fetch with rate limiting."""
        err = ApiException(status=429)
        err.headers = {"ratelimit-reset": "60"}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=err),
        ):
            result = await api_client.fetch_sites()

            assert result is None
            assert api_client.last_status == 429
            assert rate_limiter.is_limited() is True

    async def test_fetch_current_prices_success(self, api_client: AmberApiClient) -> None:
        """Test successful price fetch."""
        mock_interval = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [mock_interval]
        mock_response.headers = {"ratelimit-remaining": "45"}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await api_client.fetch_current_prices("test_site")

            assert isinstance(result, FetchResult)
            assert result.intervals is not None
            assert len(result.intervals) == 1
            assert result.status == HTTPStatus.OK
            assert result.rate_limited is False
            assert api_client.rate_limit_info.get("remaining") == 45

    async def test_fetch_current_prices_with_forecasts(self, api_client: AmberApiClient) -> None:
        """Test price fetch with forecast intervals."""
        mock_intervals = [MagicMock() for _ in range(10)]
        mock_response = MagicMock()
        mock_response.data = mock_intervals
        mock_response.headers = {}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await api_client.fetch_current_prices("test_site", next_intervals=9, resolution=30)

            assert result.intervals is not None
            assert len(result.intervals) == 10

    async def test_fetch_current_prices_rate_limited_backoff(
        self, api_client: AmberApiClient, rate_limiter: ExponentialBackoffRateLimiter
    ) -> None:
        """Test price fetch when already in rate limit backoff."""
        # Put rate limiter into backoff mode
        rate_limiter.record_rate_limit(60)

        result = await api_client.fetch_current_prices("test_site")

        assert result.intervals is None
        assert result.status == 429
        assert result.rate_limited is True

    async def test_fetch_current_prices_api_exception(self, api_client: AmberApiClient) -> None:
        """Test price fetch with API exception."""
        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=ApiException(status=503)),
        ):
            result = await api_client.fetch_current_prices("test_site")

            assert result.intervals is None
            assert result.status == 503
            assert result.rate_limited is False

    async def test_fetch_current_prices_rate_limit_triggers_backoff(
        self, api_client: AmberApiClient, rate_limiter: ExponentialBackoffRateLimiter
    ) -> None:
        """Test price fetch triggers backoff on 429."""
        err = ApiException(status=429)
        err.headers = {"ratelimit-reset": "120"}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=err),
        ):
            result = await api_client.fetch_current_prices("test_site")

            assert result.intervals is None
            assert result.status == 429
            assert result.rate_limited is True
            assert rate_limiter.is_limited() is True

    async def test_fetch_current_prices_generic_exception(self, api_client: AmberApiClient) -> None:
        """Test price fetch with generic exception."""
        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=Exception("Network error")),
        ):
            result = await api_client.fetch_current_prices("test_site")

            assert result.intervals is None
            assert result.status == HTTPStatus.INTERNAL_SERVER_ERROR

    async def test_fetch_current_prices_resets_backoff_on_success(
        self, api_client: AmberApiClient, rate_limiter: ExponentialBackoffRateLimiter
    ) -> None:
        """Test successful fetch resets rate limiter backoff."""
        # Trigger a rate limit first
        rate_limiter.record_rate_limit(5)
        # Wait for backoff to expire (simulate)
        rate_limiter._rate_limit_until = None  # Clear rate limit

        mock_response = MagicMock()
        mock_response.data = []
        mock_response.headers = {}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await api_client.fetch_current_prices("test_site")

            # Backoff should be reset
            assert rate_limiter.current_backoff == 0


class TestRateLimitHeaderParsing:
    """Tests for rate limit header parsing."""

    async def test_parse_ratelimit_headers(self, api_client: AmberApiClient) -> None:
        """Test parsing of rate limit headers."""
        mock_response = MagicMock()
        mock_response.data = []
        mock_response.headers = {
            "ratelimit-limit": "50",
            "ratelimit-remaining": "42",
            "ratelimit-reset": "180",
            "ratelimit-policy": "50;w=300",
        }

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await api_client.fetch_current_prices("test_site")

            info = api_client.rate_limit_info
            assert info.get("limit") == 50
            assert info.get("remaining") == 42
            assert info.get("reset_seconds") == 180
            assert info.get("window_seconds") == 300
            assert info.get("policy") == "50;w=300"

    async def test_parse_ratelimit_headers_case_insensitive(self, api_client: AmberApiClient) -> None:
        """Test rate limit header parsing is case insensitive."""
        mock_response = MagicMock()
        mock_response.data = []
        mock_response.headers = {
            "RateLimit-Limit": "50",
            "RATELIMIT-REMAINING": "42",
        }

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await api_client.fetch_current_prices("test_site")

            info = api_client.rate_limit_info
            assert info.get("limit") == 50
            assert info.get("remaining") == 42

    async def test_parse_empty_headers(self, api_client: AmberApiClient) -> None:
        """Test handling of empty headers."""
        mock_response = MagicMock()
        mock_response.data = []
        mock_response.headers = None

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await api_client.fetch_current_prices("test_site")

            # Should not crash, info should be empty
            assert api_client.rate_limit_info == {}
