"""Tests for the Amber API client."""

from datetime import UTC, date, datetime
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

from amberelectric.models import Site
from amberelectric.models.channel import Channel
from amberelectric.models.channel_type import ChannelType
from amberelectric.models.current_interval import CurrentInterval
from amberelectric.models.interval import Interval
from amberelectric.models.price_descriptor import PriceDescriptor
from amberelectric.models.site_status import SiteStatus
from amberelectric.models.spike_status import SpikeStatus
from amberelectric.rest import ApiException
from homeassistant.core import HomeAssistant
import pytest

from custom_components.amber_express.api_client import AmberApiClient, AmberApiError, RateLimitedError
from custom_components.amber_express.rate_limiter import ExponentialBackoffRateLimiter


def _make_interval(per_kwh: float = 25.0) -> Interval:
    """Create a test Interval object."""
    return Interval(
        actual_instance=CurrentInterval(
            type="CurrentInterval",
            duration=30,
            spot_per_kwh=5.0,
            per_kwh=per_kwh,
            date=date(2024, 1, 1),
            nem_time=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, 9, 30, 0, tzinfo=UTC),
            end_time=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            renewables=45.0,
            channel_type=ChannelType.GENERAL,
            spike_status=SpikeStatus.NONE,
            descriptor=PriceDescriptor.NEUTRAL,
            estimate=True,
        )
    )


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
        site = Site(
            id="test_site",
            nmi="1234567890",
            channels=[Channel(identifier="E1", type=ChannelType.GENERAL, tariff="A1")],
            network="Ausgrid",
            status=SiteStatus.ACTIVE,
            interval_length=30,
        )
        mock_response = MagicMock()
        mock_response.data = [site]
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
        """Test site fetch with no sites."""
        mock_response = MagicMock()
        mock_response.data = []
        mock_response.headers = {}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await api_client.fetch_sites()

            assert result == []

    async def test_fetch_sites_api_exception(self, api_client: AmberApiClient) -> None:
        """Test site fetch with API exception raises AmberApiError."""
        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=ApiException(status=500)),
        ):
            with pytest.raises(AmberApiError) as exc_info:
                await api_client.fetch_sites()

            assert exc_info.value.status == 500
            assert api_client.last_status == 500

    async def test_fetch_sites_rate_limited(
        self, api_client: AmberApiClient, rate_limiter: ExponentialBackoffRateLimiter
    ) -> None:
        """Test site fetch with rate limiting raises RateLimitedError."""
        err = ApiException(status=429)
        err.headers = {"ratelimit-reset": "60"}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=err),
        ):
            with pytest.raises(RateLimitedError) as exc_info:
                await api_client.fetch_sites()

            assert exc_info.value.reset_seconds == 60
            assert api_client.last_status == 429
            assert rate_limiter.is_limited() is True

    async def test_fetch_current_prices_success(self, api_client: AmberApiClient) -> None:
        """Test successful price fetch."""
        interval = _make_interval()
        mock_response = MagicMock()
        mock_response.data = [interval]
        mock_response.headers = {"ratelimit-remaining": "45"}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await api_client.fetch_current_prices("test_site")

            assert len(result) == 1
            assert api_client.last_status == HTTPStatus.OK
            assert api_client.rate_limit_info.get("remaining") == 45

    async def test_fetch_current_prices_with_forecasts(self, api_client: AmberApiClient) -> None:
        """Test price fetch with forecast intervals."""
        intervals = [_make_interval(per_kwh=20.0 + i) for i in range(10)]
        mock_response = MagicMock()
        mock_response.data = intervals
        mock_response.headers = {}

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await api_client.fetch_current_prices("test_site", next_intervals=9, resolution=30)

            assert len(result) == 10

    async def test_fetch_current_prices_rate_limited_backoff(
        self, api_client: AmberApiClient, rate_limiter: ExponentialBackoffRateLimiter
    ) -> None:
        """Test price fetch when already in rate limit backoff raises RateLimitedError."""
        # Put rate limiter into backoff mode
        rate_limiter.record_rate_limit(60)

        with pytest.raises(RateLimitedError):
            await api_client.fetch_current_prices("test_site")

    async def test_fetch_current_prices_api_exception(self, api_client: AmberApiClient) -> None:
        """Test price fetch with API exception raises AmberApiError."""
        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(side_effect=ApiException(status=503)),
        ):
            with pytest.raises(AmberApiError) as exc_info:
                await api_client.fetch_current_prices("test_site")

            assert exc_info.value.status == 503
            assert api_client.last_status == 503

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
            with pytest.raises(RateLimitedError) as exc_info:
                await api_client.fetch_current_prices("test_site")

            assert exc_info.value.reset_seconds == 120
            assert rate_limiter.is_limited() is True

    async def test_fetch_current_prices_resets_backoff_on_success(
        self, api_client: AmberApiClient, rate_limiter: ExponentialBackoffRateLimiter
    ) -> None:
        """Test successful fetch resets rate limiter backoff."""
        # Trigger a rate limit first
        rate_limiter.record_rate_limit(5)
        # Wait for backoff to expire (simulate)
        rate_limiter._rate_limit_until = None  # Clear rate limit

        interval = _make_interval()
        mock_response = MagicMock()
        mock_response.data = [interval]
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

    async def test_parse_invalid_policy_header(self, api_client: AmberApiClient) -> None:
        """Test handling of malformed ratelimit-policy header."""
        mock_response = MagicMock()
        mock_response.data = []
        mock_response.headers = {
            "ratelimit-policy": "invalid{{malformed",  # Invalid structured field
            "ratelimit-remaining": "42",
        }

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await api_client.fetch_current_prices("test_site")

            # Should parse remaining but skip invalid policy
            info = api_client.rate_limit_info
            assert info.get("remaining") == 42
            assert info.get("limit") is None
            assert info.get("window_seconds") is None

    async def test_parse_policy_without_window(self, api_client: AmberApiClient) -> None:
        """Test policy header with value but no window parameter."""
        mock_response = MagicMock()
        mock_response.data = []
        mock_response.headers = {
            "ratelimit-policy": "50",  # No ;w=N parameter
        }

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await api_client.fetch_current_prices("test_site")

            info = api_client.rate_limit_info
            assert info.get("limit") == 50
            assert info.get("window_seconds") is None

    async def test_parse_policy_non_int_value(self, api_client: AmberApiClient) -> None:
        """Test policy header with non-integer value."""
        mock_response = MagicMock()
        mock_response.data = []
        mock_response.headers = {
            "ratelimit-policy": '"string_value";w=300',  # String instead of int
        }

        with patch.object(
            api_client._hass,
            "async_add_executor_job",
            new=AsyncMock(return_value=mock_response),
        ):
            await api_client.fetch_current_prices("test_site")

            info = api_client.rate_limit_info
            # limit should be None since value isn't int
            assert info.get("limit") is None


class TestApiClientErrorExtraction:
    """Tests for error header extraction."""

    async def test_get_reset_from_error_no_headers(self, api_client: AmberApiClient) -> None:
        """Test _get_reset_from_error with no headers."""
        err = ApiException(status=429)
        err.headers = None

        result = api_client._get_reset_from_error(err)
        assert result is None

    async def test_get_reset_from_error_no_reset_header(self, api_client: AmberApiClient) -> None:
        """Test _get_reset_from_error with headers but no reset."""
        err = ApiException(status=429)
        err.headers = {"other-header": "value"}

        result = api_client._get_reset_from_error(err)
        assert result is None

    async def test_get_reset_from_error_invalid_reset(self, api_client: AmberApiClient) -> None:
        """Test _get_reset_from_error with invalid reset value."""
        err = ApiException(status=429)
        err.headers = {"ratelimit-reset": "not-a-number"}

        result = api_client._get_reset_from_error(err)
        assert result is None

    async def test_get_reset_from_error_valid_reset(self, api_client: AmberApiClient) -> None:
        """Test _get_reset_from_error with valid reset value."""
        err = ApiException(status=429)
        err.headers = {"ratelimit-reset": "120"}

        result = api_client._get_reset_from_error(err)
        assert result == 120

    async def test_fetch_sites_generic_exception(self, api_client: AmberApiClient) -> None:
        """Test fetch_sites with generic exception propagates."""
        with (
            patch.object(
                api_client._hass,
                "async_add_executor_job",
                new=AsyncMock(side_effect=Exception("Network error")),
            ),
            pytest.raises(Exception, match="Network error"),
        ):
            await api_client.fetch_sites()
