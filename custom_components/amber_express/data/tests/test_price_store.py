"""Tests for the interval-keyed price store and its derived view."""

from datetime import UTC, datetime, timedelta

from custom_components.amber_express.const import (
    ATTR_DEMAND_WINDOW,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECAST,
    ATTR_NEM_TIME,
    ATTR_PER_KWH,
    ATTR_START_TIME,
    CHANNEL_GENERAL,
)
from custom_components.amber_express.data import PriceStore
from custom_components.amber_express.types import ChannelData

T1000 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
T1005 = T1000 + timedelta(minutes=5)
T1010 = T1005 + timedelta(minutes=5)


def price(start: datetime, per_kwh: float, *, estimate: bool) -> ChannelData:
    """Build interval data the way Amber reports it, starting one second past the boundary."""
    end = start + timedelta(minutes=5)
    return {
        ATTR_PER_KWH: per_kwh,
        ATTR_ESTIMATE: estimate,
        ATTR_START_TIME: (start + timedelta(seconds=1)).isoformat(),
        ATTR_END_TIME: end.isoformat(),
        ATTR_NEM_TIME: end.isoformat(),
    }


def polling_response(current: ChannelData, *forecasts: ChannelData) -> dict[str, ChannelData]:
    """Build a polling response with the current interval repeated as the first forecast."""
    return {CHANNEL_GENERAL: {**current, ATTR_FORECAST: [current, *forecasts]}}


class TestCurrentPrice:
    """The view shows the record for the interval the clock is in."""

    def test_confirmed_price_for_current_interval_is_shown(self) -> None:
        """A confirmed price is always shown."""
        store = PriceStore()
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")

        view = store.view(T1000, publish_estimates=False)

        assert view.channels[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25
        assert view.channels[CHANNEL_GENERAL][ATTR_ESTIMATE] is False

    def test_estimate_is_shown_when_publishing_estimates(self) -> None:
        """An estimate is shown once estimates are publishable."""
        store = PriceStore()
        store.record(polling_response(price(T1000, 0.25, estimate=True)), source="polling")

        view = store.view(T1000, publish_estimates=True)

        assert view.channels[CHANNEL_GENERAL][ATTR_PER_KWH] == 0.25
        assert view.channels[CHANNEL_GENERAL][ATTR_ESTIMATE] is True


class TestConfirmation:
    """Confirmation is a fact about a specific interval, not a flag reset at the boundary."""

    def test_confirmed_previous_interval_does_not_confirm_current_interval(self) -> None:
        """A late confirmed response for 10:00 leaves 10:05 unconfirmed."""
        store = PriceStore()
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")

        assert store.is_confirmed(T1000)
        assert not store.is_confirmed(T1005)


class TestRetention:
    """Old intervals are discarded explicitly."""

    def test_discarded_intervals_can_no_longer_be_held(self) -> None:
        """After discarding 10:00 there is no earlier price to hold for 10:05."""
        store = PriceStore()
        store.record(
            polling_response(price(T1000, 0.25, estimate=False), price(T1005, 0.40, estimate=True)),
            source="polling",
        )

        store.discard_before(T1005)

        assert ATTR_PER_KWH not in store.view(T1005, publish_estimates=False).channels[CHANNEL_GENERAL]


class TestSource:
    """The view reports which source supplied the general channel's shown price."""

    def test_source_follows_shown_price(self) -> None:
        """A confirmed WebSocket price replaces a polling estimate as the shown source."""
        store = PriceStore()
        store.record(polling_response(price(T1000, 0.25, estimate=True)), source="polling")
        store.record({CHANNEL_GENERAL: price(T1000, 0.26, estimate=False)}, source="websocket")

        assert store.view(T1000, publish_estimates=False).source == "websocket"

    def test_held_price_reports_source_of_price_it_holds(self) -> None:
        """A held price came from the source of the earlier interval."""
        store = PriceStore()
        store.record({CHANNEL_GENERAL: price(T1000, 0.25, estimate=False)}, source="websocket")
        store.record(polling_response(price(T1005, 0.40, estimate=True)), source="polling")

        assert store.view(T1005, publish_estimates=False).source == "websocket"


class TestForecast:
    """The forecast list starts at the shown current interval and continues with later intervals."""

    def test_forecast_starts_with_held_price_and_drops_past_intervals(self) -> None:
        """Past intervals never appear, and the first entry matches what the sensor shows."""
        store = PriceStore()
        store.record(
            polling_response(
                price(T1000, 0.25, estimate=False),
                price(T1005, 0.40, estimate=True),
                price(T1010, 0.50, estimate=True),
            ),
            source="polling",
        )

        general = store.view(T1005, publish_estimates=False).channels[CHANNEL_GENERAL]

        assert [(f[ATTR_START_TIME], f[ATTR_PER_KWH]) for f in general[ATTR_FORECAST]] == [
            (price(T1005, 0, estimate=True)[ATTR_START_TIME], 0.25),
            (price(T1010, 0, estimate=True)[ATTR_START_TIME], 0.50),
        ]


class TestMissingData:
    """Without a publishable or holdable price, the view shows no current price."""

    def test_no_current_price_without_earlier_price_to_hold(self) -> None:
        """At startup an unconfirmed estimate has nothing to hold, so only forecasts are shown."""
        store = PriceStore()
        store.record(
            polling_response(price(T1005, 0.40, estimate=True), price(T1010, 0.50, estimate=True)),
            source="polling",
        )

        general = store.view(T1005, publish_estimates=False).channels[CHANNEL_GENERAL]

        assert ATTR_PER_KWH not in general
        assert [f[ATTR_PER_KWH] for f in general[ATTR_FORECAST]] == [0.50]

    def test_no_current_price_when_nothing_is_known_about_current_interval(self) -> None:
        """Without any record for the current interval there is no timing to hold a price against."""
        store = PriceStore()
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")

        general = store.view(T1005, publish_estimates=True).channels[CHANNEL_GENERAL]

        assert ATTR_PER_KWH not in general
        assert general[ATTR_FORECAST] == []


class TestHeldPrice:
    """Until the current interval is publishable, the previous price is held with current timing."""

    def test_estimate_is_held_back_while_waiting_for_confirmed(self) -> None:
        """While waiting, the previous price is shown for the current interval."""
        store = PriceStore()
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")
        store.record(polling_response(price(T1005, 0.40, estimate=True)), source="polling")

        general = store.view(T1005, publish_estimates=False).channels[CHANNEL_GENERAL]

        assert general[ATTR_PER_KWH] == 0.25
        assert general[ATTR_ESTIMATE] is True
        assert general[ATTR_START_TIME] == price(T1005, 0.40, estimate=True)[ATTR_START_TIME]

    def test_held_price_takes_demand_window_from_current_interval(self) -> None:
        """The demand window belongs to the interval, not to the held price."""
        store = PriceStore()
        store.record(
            polling_response(
                {**price(T1000, 0.25, estimate=False), ATTR_DEMAND_WINDOW: True},
                price(T1005, 0.40, estimate=True),
            ),
            source="polling",
        )

        general = store.view(T1005, publish_estimates=False).channels[CHANNEL_GENERAL]

        assert ATTR_DEMAND_WINDOW not in general

    def test_late_response_for_previous_interval_does_not_replace_current_estimate(self) -> None:
        """A response that crossed the boundary only adds a forecast, which ranks below an estimate."""
        store = PriceStore()
        store.record(polling_response(price(T1005, 0.40, estimate=True)), source="polling")
        store.record(
            polling_response(price(T1000, 0.25, estimate=False), price(T1005, 0.30, estimate=True)),
            source="polling",
        )

        general = store.view(T1005, publish_estimates=True).channels[CHANNEL_GENERAL]

        assert general[ATTR_PER_KWH] == 0.40

    def test_websocket_estimate_is_held_back_while_waiting_for_confirmed(self) -> None:
        """WebSocket data goes through the same rules as polling data."""
        store = PriceStore()
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")
        store.record({CHANNEL_GENERAL: price(T1005, 0.40, estimate=True)}, source="websocket")

        general = store.view(T1005, publish_estimates=False).channels[CHANNEL_GENERAL]

        assert general[ATTR_PER_KWH] == 0.25
        assert general[ATTR_ESTIMATE] is True

    def test_price_is_held_after_timeout_when_nothing_arrived_for_current_interval(self) -> None:
        """A forecast is not a current price, so the timeout cannot publish the previous interval as confirmed."""
        store = PriceStore()
        store.record(
            polling_response(price(T1000, 0.25, estimate=False), price(T1005, 0.40, estimate=True)),
            source="polling",
        )

        general = store.view(T1005, publish_estimates=True).channels[CHANNEL_GENERAL]

        assert general[ATTR_PER_KWH] == 0.25
        assert general[ATTR_ESTIMATE] is True
        assert general[ATTR_START_TIME] == price(T1005, 0.40, estimate=True)[ATTR_START_TIME]
