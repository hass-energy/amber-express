"""Tests for the interval processor."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from amberelectric.models import CurrentInterval, ForecastInterval, Interval
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


@pytest.fixture
def mock_current_interval() -> MagicMock:
    """Create a mock current interval."""
    interval = MagicMock(spec=CurrentInterval)
    interval.per_kwh = 25.0
    interval.spot_per_kwh = 20.0
    interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    interval.nem_time = "2024-01-01T10:00:00+10:00"
    interval.renewables = 45.0
    interval.descriptor = MagicMock(value="neutral")
    interval.spike_status = MagicMock(value="none")
    interval.estimate = False
    interval.channel_type = MagicMock(value="general")
    interval.advanced_price = None
    interval.tariff_information = None
    return interval


@pytest.fixture
def mock_forecast_interval() -> MagicMock:
    """Create a mock forecast interval."""
    interval = MagicMock(spec=ForecastInterval)
    interval.per_kwh = 26.0
    interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    interval.end_time = datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC)
    interval.channel_type = MagicMock(value="general")
    interval.advanced_price = None
    interval.tariff_information = None
    return interval


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

    def test_extract_interval_data(self, processor: IntervalProcessor, mock_current_interval: MagicMock) -> None:
        """Test _extract_interval_data."""
        result = processor._extract_interval_data(mock_current_interval)

        assert result[ATTR_PER_KWH] == 0.25
        assert result[ATTR_SPOT_PER_KWH] == 0.20
        assert result[ATTR_RENEWABLES] == 45.0
        assert result[ATTR_DESCRIPTOR] == "neutral"
        assert result[ATTR_SPIKE_STATUS] == "none"
        assert result[ATTR_ESTIMATE] is False

    def test_extract_interval_data_with_advanced_price(
        self, processor: IntervalProcessor, mock_current_interval: MagicMock
    ) -> None:
        """Test _extract_interval_data with advanced price."""
        mock_current_interval.advanced_price = MagicMock()
        mock_current_interval.advanced_price.low = 20.0
        mock_current_interval.advanced_price.predicted = 25.0
        mock_current_interval.advanced_price.high = 30.0

        result = processor._extract_interval_data(mock_current_interval)

        assert result[ATTR_ADVANCED_PRICE]["low"] == 0.20
        assert result[ATTR_ADVANCED_PRICE]["predicted"] == 0.25
        assert result[ATTR_ADVANCED_PRICE]["high"] == 0.30

    def test_extract_interval_data_with_tariff_info(
        self, processor: IntervalProcessor, mock_current_interval: MagicMock
    ) -> None:
        """Test _extract_interval_data with tariff information."""
        mock_current_interval.tariff_information = MagicMock()
        mock_current_interval.tariff_information.demand_window = True
        mock_current_interval.tariff_information.period = "peak"
        mock_current_interval.tariff_information.season = "summer"
        mock_current_interval.tariff_information.block = 1

        result = processor._extract_interval_data(mock_current_interval)

        assert result[ATTR_DEMAND_WINDOW] is True
        assert result[ATTR_TARIFF_PERIOD] == "peak"
        assert result[ATTR_TARIFF_SEASON] == "summer"
        assert result[ATTR_TARIFF_BLOCK] == 1

    def test_extract_interval_data_forecast_always_estimated(
        self, processor: IntervalProcessor, mock_forecast_interval: MagicMock
    ) -> None:
        """Test _extract_interval_data marks forecasts as estimated."""
        result = processor._extract_interval_data(mock_forecast_interval)
        assert result[ATTR_ESTIMATE] is True

    def test_extract_interval_data_app_mode_no_advanced_price(self, processor_app_mode: IntervalProcessor) -> None:
        """Test _extract_interval_data in APP mode falls back to per_kwh."""
        interval = MagicMock(spec=CurrentInterval)
        interval.per_kwh = 25.0
        interval.spot_per_kwh = 20.0
        interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.nem_time = None
        interval.renewables = None
        interval.descriptor = None
        interval.spike_status = None
        interval.estimate = False
        interval.advanced_price = None
        interval.tariff_information = None

        result = processor_app_mode._extract_interval_data(interval)
        assert result[ATTR_PER_KWH] == 0.25

    def test_extract_interval_data_app_mode_advanced_price_no_predicted(
        self, processor_app_mode: IntervalProcessor
    ) -> None:
        """Test _extract_interval_data in APP mode with advanced_price but no predicted."""
        interval = MagicMock(spec=CurrentInterval)
        interval.per_kwh = 25.0
        interval.spot_per_kwh = 20.0
        interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.nem_time = None
        interval.renewables = None
        interval.descriptor = None
        interval.spike_status = None
        interval.estimate = False
        interval.advanced_price = MagicMock()
        interval.advanced_price.predicted = None
        interval.advanced_price.low = 20.0
        interval.advanced_price.high = 30.0
        interval.tariff_information = None

        result = processor_app_mode._extract_interval_data(interval)
        assert result[ATTR_PER_KWH] == 0.25


class TestBuildForecasts:
    """Tests for _build_forecasts method."""

    def test_build_forecasts(self, processor: IntervalProcessor, mock_forecast_interval: MagicMock) -> None:
        """Test _build_forecasts."""
        result = processor._build_forecasts([mock_forecast_interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.26

    def test_build_forecasts_with_advanced_price(self, processor: IntervalProcessor) -> None:
        """Test _build_forecasts includes advanced_price when available."""
        interval = MagicMock(spec=ForecastInterval)
        interval.per_kwh = 26.0
        interval.spot_per_kwh = 20.0
        interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.end_time = datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC)
        interval.nem_time = None
        interval.renewables = 45.0
        interval.descriptor = None
        interval.spike_status = None
        interval.advanced_price = MagicMock()
        interval.advanced_price.low = 25.0
        interval.advanced_price.predicted = 27.0
        interval.advanced_price.high = 29.0
        interval.tariff_information = None

        result = processor._build_forecasts([interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.26
        assert result[0][ATTR_ADVANCED_PRICE]["predicted"] == 0.27
        assert result[0][ATTR_RENEWABLES] == 45.0

    def test_build_forecasts_app_pricing_mode(self, processor_app_mode: IntervalProcessor) -> None:
        """Test _build_forecasts uses advanced_price in APP pricing mode."""
        interval = MagicMock(spec=ForecastInterval)
        interval.per_kwh = 26.0
        interval.spot_per_kwh = 20.0
        interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.end_time = datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC)
        interval.nem_time = None
        interval.renewables = None
        interval.descriptor = None
        interval.spike_status = None
        interval.advanced_price = MagicMock()
        interval.advanced_price.low = 28.0
        interval.advanced_price.predicted = 30.0
        interval.advanced_price.high = 32.0
        interval.tariff_information = None

        result = processor_app_mode._build_forecasts([interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.30

    def test_build_forecasts_app_mode_no_advanced_price(self, processor_app_mode: IntervalProcessor) -> None:
        """Test _build_forecasts in APP mode falls back to per_kwh."""
        interval = MagicMock(spec=ForecastInterval)
        interval.per_kwh = 26.0
        interval.spot_per_kwh = 20.0
        interval.start_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        interval.end_time = datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC)
        interval.nem_time = None
        interval.renewables = None
        interval.descriptor = None
        interval.spike_status = None
        interval.advanced_price = None
        interval.tariff_information = None

        result = processor_app_mode._build_forecasts([interval])
        assert len(result) == 1
        assert result[0][ATTR_PER_KWH] == 0.26


class TestProcessIntervals:
    """Tests for process_intervals method."""

    def test_process_intervals_current_only(self, processor: IntervalProcessor) -> None:
        """Test process_intervals with current interval only."""
        inner_interval = MagicMock(spec=CurrentInterval)
        inner_interval.per_kwh = 25.0
        inner_interval.spot_per_kwh = 20.0
        inner_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        inner_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        inner_interval.nem_time = None
        inner_interval.renewables = None
        inner_interval.descriptor = None
        inner_interval.spike_status = None
        inner_interval.estimate = False
        inner_interval.channel_type = MagicMock(value="general")
        inner_interval.advanced_price = None
        inner_interval.tariff_information = None

        wrapper = MagicMock(spec=Interval)
        wrapper.actual_instance = inner_interval

        result = processor.process_intervals([wrapper])

        assert CHANNEL_GENERAL in result
        assert result[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25
        assert ATTR_FORECASTS in result[CHANNEL_GENERAL]

    def test_process_intervals_with_wrapper(self, processor: IntervalProcessor) -> None:
        """Test process_intervals unwraps Interval wrapper."""
        inner_interval = MagicMock(spec=CurrentInterval)
        inner_interval.per_kwh = 25.0
        inner_interval.spot_per_kwh = 20.0
        inner_interval.start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        inner_interval.end_time = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        inner_interval.nem_time = None
        inner_interval.renewables = None
        inner_interval.descriptor = None
        inner_interval.spike_status = None
        inner_interval.estimate = False
        inner_interval.channel_type = MagicMock(value="general")
        inner_interval.advanced_price = None
        inner_interval.tariff_information = None

        wrapper = MagicMock(spec=Interval)
        wrapper.actual_instance = inner_interval

        result = processor.process_intervals([wrapper])

        assert CHANNEL_GENERAL in result
        assert result[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25

    def test_process_intervals_skips_none_wrapper(self, processor: IntervalProcessor) -> None:
        """Test process_intervals skips None in wrapper."""
        wrapper = MagicMock(spec=Interval)
        wrapper.actual_instance = None

        result = processor.process_intervals([wrapper])

        assert result == {}

    def test_process_intervals_missing_channel_type(self, processor: IntervalProcessor) -> None:
        """Test process_intervals skips intervals without channel_type attribute."""
        inner_interval = MagicMock()
        # Remove channel_type attribute entirely
        del inner_interval.channel_type

        wrapper = MagicMock(spec=Interval)
        wrapper.actual_instance = inner_interval

        result = processor.process_intervals([wrapper])
        assert result == {}
