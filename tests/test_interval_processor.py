"""Tests for the interval processor."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

from amberelectric.models import CurrentInterval, ForecastInterval, Interval
from amberelectric.models.actual_interval import ActualInterval
from amberelectric.models.advanced_price import AdvancedPrice
from amberelectric.models.channel_type import ChannelType
from amberelectric.models.price_descriptor import PriceDescriptor
from amberelectric.models.spike_status import SpikeStatus
from amberelectric.models.tariff_information import TariffInformation
import pytest

from custom_components.amber_express.const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DESCRIPTOR,
    ATTR_ESTIMATE,
    ATTR_FORECASTS,
    ATTR_PER_KWH,
    ATTR_RENEWABLES,
    ATTR_SPIKE_STATUS,
    ATTR_SPOT_PER_KWH,
    ATTR_TARIFF_BLOCK,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_GENERAL,
    PRICING_MODE_AEMO,
    PRICING_MODE_APP,
)
from custom_components.amber_express.interval_processor import CHANNEL_TYPE_MAP, IntervalProcessor


def _make_current_interval(
    *,
    per_kwh: float = 25.0,
    spot_per_kwh: float = 20.0,
    renewables: float = 45.0,
    estimate: bool = False,
    channel_type: ChannelType = ChannelType.GENERAL,
    descriptor: PriceDescriptor = PriceDescriptor.NEUTRAL,
    spike_status: SpikeStatus = SpikeStatus.NONE,
    advanced_price: AdvancedPrice | None = None,
    tariff_information: TariffInformation | None = None,
) -> CurrentInterval:
    """Create a test CurrentInterval object."""
    return CurrentInterval(
        type="CurrentInterval",
        duration=30,
        spot_per_kwh=spot_per_kwh,
        per_kwh=per_kwh,
        var_date=date(2024, 1, 1),
        nem_time=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, 9, 30, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
        renewables=renewables,
        channel_type=channel_type,
        spike_status=spike_status,
        descriptor=descriptor,
        estimate=estimate,
        advanced_price=advanced_price,
        tariff_information=tariff_information,
    )


def _make_forecast_interval(
    *,
    per_kwh: float = 26.0,
    spot_per_kwh: float = 20.0,
    renewables: float = 45.0,
    channel_type: ChannelType = ChannelType.GENERAL,
    descriptor: PriceDescriptor = PriceDescriptor.NEUTRAL,
    spike_status: SpikeStatus = SpikeStatus.NONE,
    start_time: datetime | None = None,
    advanced_price: AdvancedPrice | None = None,
    tariff_information: TariffInformation | None = None,
) -> ForecastInterval:
    """Create a test ForecastInterval object."""
    start = start_time or datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    return ForecastInterval(
        type="ForecastInterval",
        duration=30,
        spot_per_kwh=spot_per_kwh,
        per_kwh=per_kwh,
        var_date=date(2024, 1, 1),
        nem_time=datetime(2024, 1, 1, 10, 30, 0, tzinfo=UTC),
        start_time=start,
        end_time=end,
        renewables=renewables,
        channel_type=channel_type,
        spike_status=spike_status,
        descriptor=descriptor,
        advanced_price=advanced_price,
        tariff_information=tariff_information,
    )


@pytest.fixture
def current_interval() -> CurrentInterval:
    """Create a current interval for testing."""
    return _make_current_interval()


@pytest.fixture
def forecast_interval() -> ForecastInterval:
    """Create a forecast interval for testing."""
    return _make_forecast_interval()


@pytest.fixture
def processor() -> IntervalProcessor:
    """Create an interval processor with AEMO pricing mode."""
    return IntervalProcessor(PRICING_MODE_AEMO)


@pytest.fixture
def processor_app_mode() -> IntervalProcessor:
    """Create an interval processor with APP pricing mode."""
    return IntervalProcessor(PRICING_MODE_APP)


class TestChannelTypeMapping:
    """Tests for channel type mapping."""

    def test_channel_type_mapping(self) -> None:
        """Test channel type mapping."""
        assert CHANNEL_TYPE_MAP["general"] == "general"
        assert CHANNEL_TYPE_MAP["feedIn"] == "feed_in"
        assert CHANNEL_TYPE_MAP["controlledLoad"] == "controlled_load"


class TestExtractIntervalData:
    """Tests for _extract_interval_data method."""

    def test_extract_interval_data(self, processor: IntervalProcessor, current_interval: CurrentInterval) -> None:
        """Test _extract_interval_data."""
        result = processor._extract_interval_data(current_interval)

        assert result[ATTR_PER_KWH] == 0.25
        assert result[ATTR_SPOT_PER_KWH] == 0.20
        assert result[ATTR_RENEWABLES] == 45.0
        assert result[ATTR_DESCRIPTOR] == "neutral"
        assert result[ATTR_SPIKE_STATUS] == "none"
        assert result[ATTR_ESTIMATE] is False

    def test_extract_interval_data_with_advanced_price(self, processor: IntervalProcessor) -> None:
        """Test _extract_interval_data with advanced price."""
        interval = _make_current_interval(advanced_price=AdvancedPrice(low=20.0, predicted=25.0, high=30.0))

        result = processor._extract_interval_data(interval)

        assert result[ATTR_ADVANCED_PRICE]["low"] == 0.20
        assert result[ATTR_ADVANCED_PRICE]["predicted"] == 0.25
        assert result[ATTR_ADVANCED_PRICE]["high"] == 0.30

    def test_extract_interval_data_with_tariff_info(self, processor: IntervalProcessor) -> None:
        """Test _extract_interval_data with tariff information."""
        interval = _make_current_interval(
            tariff_information=TariffInformation(
                demand_window=True,
                period="peak",
                season="summer",
                block=1,
            )
        )

        result = processor._extract_interval_data(interval)

        assert result[ATTR_DEMAND_WINDOW] is True
        assert result[ATTR_TARIFF_PERIOD] == "peak"
        assert result[ATTR_TARIFF_SEASON] == "summer"
        assert result[ATTR_TARIFF_BLOCK] == 1

    def test_extract_interval_data_forecast_always_estimated(
        self, processor: IntervalProcessor, forecast_interval: ForecastInterval
    ) -> None:
        """Test _extract_interval_data marks forecasts as estimated."""
        result = processor._extract_interval_data(forecast_interval)
        assert result[ATTR_ESTIMATE] is True

    def test_extract_interval_data_app_mode_no_advanced_price(self, processor_app_mode: IntervalProcessor) -> None:
        """Test _extract_interval_data in APP mode falls back to per_kwh."""
        interval = _make_current_interval(per_kwh=25.0)

        result = processor_app_mode._extract_interval_data(interval)
        assert result[ATTR_PER_KWH] == 0.25

    def test_extract_interval_data_app_mode_uses_advanced_price(self, processor_app_mode: IntervalProcessor) -> None:
        """Test _extract_interval_data in APP mode uses advanced_price.predicted."""
        interval = _make_current_interval(
            per_kwh=25.0,
            advanced_price=AdvancedPrice(low=20.0, predicted=30.0, high=35.0),
        )

        result = processor_app_mode._extract_interval_data(interval)
        # Should use advanced_price.predicted (30.0 cents = 0.30 dollars)
        assert result[ATTR_PER_KWH] == 0.30


class TestBuildForecasts:
    """Tests for _build_forecasts method."""

    def test_build_forecasts(self, processor: IntervalProcessor, forecast_interval: ForecastInterval) -> None:
        """Test _build_forecasts."""
        result = processor._build_forecasts([forecast_interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.26

    def test_build_forecasts_with_advanced_price(self, processor: IntervalProcessor) -> None:
        """Test _build_forecasts includes advanced_price when available."""
        interval = _make_forecast_interval(
            per_kwh=26.0,
            renewables=45.0,
            advanced_price=AdvancedPrice(low=25.0, predicted=27.0, high=29.0),
        )

        result = processor._build_forecasts([interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.26
        assert result[0][ATTR_ADVANCED_PRICE]["predicted"] == 0.27
        assert result[0][ATTR_RENEWABLES] == 45.0

    def test_build_forecasts_app_pricing_mode(self, processor_app_mode: IntervalProcessor) -> None:
        """Test _build_forecasts uses advanced_price in APP pricing mode."""
        interval = _make_forecast_interval(
            per_kwh=26.0,
            advanced_price=AdvancedPrice(low=28.0, predicted=30.0, high=32.0),
        )

        result = processor_app_mode._build_forecasts([interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.30

    def test_build_forecasts_app_mode_no_advanced_price(self, processor_app_mode: IntervalProcessor) -> None:
        """Test _build_forecasts in APP mode falls back to per_kwh."""
        interval = _make_forecast_interval(per_kwh=26.0)

        result = processor_app_mode._build_forecasts([interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.26


class TestProcessIntervals:
    """Tests for process_intervals method."""

    def test_process_intervals_current_only(self, processor: IntervalProcessor) -> None:
        """Test process_intervals with current interval only."""
        inner_interval = _make_current_interval(per_kwh=25.0)
        wrapper = Interval(actual_instance=inner_interval)

        result = processor.process_intervals([wrapper])

        assert CHANNEL_GENERAL in result
        assert result[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25
        assert ATTR_FORECASTS in result[CHANNEL_GENERAL]

    def test_process_intervals_with_wrapper(self, processor: IntervalProcessor) -> None:
        """Test process_intervals unwraps Interval wrapper."""
        inner_interval = _make_current_interval(per_kwh=25.0)
        wrapper = Interval(actual_instance=inner_interval)

        result = processor.process_intervals([wrapper])

        assert CHANNEL_GENERAL in result
        assert result[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25

    def test_process_intervals_skips_none_wrapper(self, processor: IntervalProcessor) -> None:
        """Test process_intervals skips None in wrapper."""
        # Use MagicMock to bypass SDK validation (SDK doesn't allow None actual_instance)
        wrapper = MagicMock(spec=Interval)
        wrapper.actual_instance = None

        result = processor.process_intervals([wrapper])

        assert result == {}

    def test_process_intervals_skips_actual_intervals(self, processor: IntervalProcessor) -> None:
        """Test process_intervals skips ActualInterval (historical data)."""
        # ActualInterval is not CurrentInterval or ForecastInterval, so it should be skipped
        # Use MagicMock since we can't easily construct an ActualInterval
        wrapper = MagicMock(spec=Interval)
        wrapper.actual_instance = MagicMock(spec=ActualInterval)

        result = processor.process_intervals([wrapper])
        assert result == {}
