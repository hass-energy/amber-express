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
    ATTR_TARIFF_BLOCK,
    ATTR_TARIFF_PERIOD,
    ATTR_TARIFF_SEASON,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
)
from custom_components.amber_express.data import HoldPolicy, PriceStore, confirms_interval
from custom_components.amber_express.types import ChannelData

FIVE_MINUTES = timedelta(minutes=5)
T1000 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
T1005 = T1000 + FIVE_MINUTES
T1010 = T1005 + FIVE_MINUTES

HOLD_FOR_45S = HoldPolicy(timeout=timedelta(seconds=45))
HOLD_UNTIL_CONFIRMED = HoldPolicy(timeout=None)

WHILE_HOLDING = T1005 + timedelta(seconds=10)
AFTER_TIMEOUT = T1005 + timedelta(seconds=60)


def price(start: datetime, per_kwh: float, *, estimate: bool) -> ChannelData:
    """Build interval data the way Amber reports it, starting one second past the boundary."""
    end = start + FIVE_MINUTES
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


def websocket_message(current: ChannelData) -> dict[str, ChannelData]:
    """Build a WebSocket message, which carries the current interval only."""
    return {CHANNEL_GENERAL: current}


def general_at(store: PriceStore, now: datetime) -> ChannelData:
    """Return what the general channel shows at the given time."""
    return store.view(now).channels[CHANNEL_GENERAL]


class TestConfirmedPrice:
    """A confirmed price for the current interval is always shown, whatever its source."""

    def test_confirmed_price_is_shown_while_holding(self) -> None:
        """Holding never hides a confirmed price."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")
        store.record(websocket_message(price(T1005, 0.30, estimate=False)), source="websocket")

        general = general_at(store, WHILE_HOLDING)

        assert general[ATTR_PER_KWH] == 0.30
        assert general[ATTR_ESTIMATE] is False


class TestBestEstimate:
    """Without a hold, or once it times out, the best estimate for the current interval is shown."""

    def test_forecast_is_shown_at_boundary_without_hold(self) -> None:
        """Before Amber reports the new interval, its latest forecast is the best estimate."""
        store = PriceStore(FIVE_MINUTES, hold=None)
        store.record(
            polling_response(price(T1000, 0.25, estimate=False), price(T1005, 0.40, estimate=True)),
            source="polling",
        )

        general = general_at(store, T1005)

        assert general[ATTR_PER_KWH] == 0.40
        assert general[ATTR_ESTIMATE] is True
        assert general[ATTR_START_TIME] == price(T1005, 0, estimate=True)[ATTR_START_TIME]

    def test_forecast_is_shown_after_timeout_when_amber_has_not_reported_current_interval(self) -> None:
        """The timeout never republishes the previous interval as confirmed."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(
            polling_response(price(T1000, 0.25, estimate=False), price(T1005, 0.40, estimate=True)),
            source="polling",
        )

        general = general_at(store, AFTER_TIMEOUT)

        assert general[ATTR_PER_KWH] == 0.40
        assert general[ATTR_ESTIMATE] is True
        assert general[ATTR_START_TIME] == price(T1005, 0, estimate=True)[ATTR_START_TIME]

    def test_amber_estimate_beats_forecast_even_when_forecast_arrives_later(self) -> None:
        """A response that crossed the boundary only adds a forecast, which ranks below an estimate."""
        store = PriceStore(FIVE_MINUTES, hold=None)
        store.record(polling_response(price(T1005, 0.40, estimate=True)), source="polling")
        store.record(
            polling_response(price(T1000, 0.25, estimate=False), price(T1005, 0.30, estimate=True)),
            source="polling",
        )

        assert general_at(store, T1005)[ATTR_PER_KWH] == 0.40

    def test_latest_forecast_replaces_older_forecast(self) -> None:
        """Among forecasts for the same interval, the newest wins."""
        store = PriceStore(FIVE_MINUTES, hold=None)
        store.record(polling_response(price(T1000, 0.25, estimate=True), price(T1005, 0.40, estimate=True)), "polling")
        store.record(polling_response(price(T1000, 0.25, estimate=True), price(T1005, 0.45, estimate=True)), "polling")

        assert general_at(store, T1005)[ATTR_PER_KWH] == 0.45


class TestHeldPrice:
    """While holding, the previous interval's final view is shown with the current interval's timing."""

    def test_estimate_is_held_back_while_holding(self) -> None:
        """Amber's estimate is not shown before the timeout."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")
        store.record(websocket_message(price(T1005, 0.40, estimate=True)), source="websocket")

        general = general_at(store, WHILE_HOLDING)

        assert general[ATTR_PER_KWH] == 0.25
        assert general[ATTR_ESTIMATE] is True
        assert general[ATTR_START_TIME] == price(T1005, 0, estimate=True)[ATTR_START_TIME]

    def test_hold_continues_what_the_previous_interval_ended_on(self) -> None:
        """If the previous interval timed out on an estimate, that estimate is held rather than flipping back."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")
        store.record(polling_response(price(T1005, 0.40, estimate=True), price(T1010, 0.50, estimate=True)), "polling")

        assert general_at(store, T1010 + timedelta(seconds=10))[ATTR_PER_KWH] == 0.40

    def test_hold_until_confirmed_chains_back_to_last_confirmed_price(self) -> None:
        """Without a timeout an unconfirmed interval was itself held, so the hold reaches the last confirmed price."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_UNTIL_CONFIRMED)
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")
        store.record(polling_response(price(T1005, 0.40, estimate=True), price(T1010, 0.50, estimate=True)), "polling")

        assert general_at(store, T1010 + timedelta(minutes=4))[ATTR_PER_KWH] == 0.25

    def test_held_price_takes_demand_window_from_current_interval(self) -> None:
        """The demand window belongs to the interval, not to the held price."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(
            polling_response(
                {**price(T1000, 0.25, estimate=False), ATTR_DEMAND_WINDOW: True},
                price(T1005, 0.40, estimate=True),
            ),
            source="polling",
        )

        assert ATTR_DEMAND_WINDOW not in general_at(store, WHILE_HOLDING)

    def test_held_price_takes_tariff_from_current_interval(self) -> None:
        """At a tariff boundary the held price shows the new period alongside the new times."""
        offpeak: ChannelData = {ATTR_TARIFF_PERIOD: "offPeak", ATTR_TARIFF_SEASON: "winter", ATTR_TARIFF_BLOCK: 1}
        peak: ChannelData = {ATTR_TARIFF_PERIOD: "peak", ATTR_TARIFF_SEASON: "summer", ATTR_TARIFF_BLOCK: 2}
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(
            polling_response(
                {**price(T1000, 0.25, estimate=False), **offpeak}, {**price(T1005, 0.40, estimate=True), **peak}
            ),
            source="polling",
        )

        general = general_at(store, WHILE_HOLDING)

        assert general[ATTR_PER_KWH] == 0.25
        assert {key: general[key] for key in peak} == peak


class TestMissingData:
    """Without anything to show or hold, the view shows no current price."""

    def test_no_current_price_without_earlier_interval_to_hold(self) -> None:
        """At startup an unconfirmed estimate has nothing to hold, so only later forecasts are shown."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(
            polling_response(price(T1005, 0.40, estimate=True), price(T1010, 0.50, estimate=True)),
            source="polling",
        )

        general = general_at(store, WHILE_HOLDING)

        assert ATTR_PER_KWH not in general
        assert [f[ATTR_PER_KWH] for f in general[ATTR_FORECAST]] == [0.50]

    def test_no_current_price_when_nothing_is_known_about_current_interval(self) -> None:
        """Without any record for the current interval there is nothing to show and no timing to hold against."""
        store = PriceStore(FIVE_MINUTES, hold=None)
        store.record(polling_response(price(T1000, 0.25, estimate=False)), source="polling")

        general = general_at(store, T1005)

        assert ATTR_PER_KWH not in general
        assert general[ATTR_FORECAST] == []


class TestForecast:
    """The forecast list starts at the shown current interval and continues with later intervals."""

    def test_forecast_starts_with_shown_price_and_drops_past_intervals(self) -> None:
        """Past intervals never appear, and the first entry matches what the sensor shows."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(
            polling_response(
                price(T1000, 0.25, estimate=False),
                price(T1005, 0.40, estimate=True),
                price(T1010, 0.50, estimate=True),
            ),
            source="polling",
        )

        forecast = general_at(store, WHILE_HOLDING)[ATTR_FORECAST]

        assert [(f[ATTR_START_TIME], f[ATTR_PER_KWH]) for f in forecast] == [
            (price(T1005, 0, estimate=True)[ATTR_START_TIME], 0.25),
            (price(T1010, 0, estimate=True)[ATTR_START_TIME], 0.50),
        ]

    def test_view_reports_its_interval_start(self) -> None:
        """The view's interval start is the baseline for how far forecasts reach."""
        store = PriceStore(FIVE_MINUTES, hold=None)

        assert store.view(WHILE_HOLDING).interval_start == T1005


class TestSource:
    """The view reports which source supplied the general channel's shown price."""

    def test_source_follows_shown_price(self) -> None:
        """A confirmed WebSocket price replaces a polling estimate as the shown source."""
        store = PriceStore(FIVE_MINUTES, hold=None)
        store.record(polling_response(price(T1005, 0.25, estimate=True)), source="polling")
        store.record(websocket_message(price(T1005, 0.26, estimate=False)), source="websocket")

        assert store.view(WHILE_HOLDING).source == "websocket"

    def test_held_price_reports_source_of_price_it_holds(self) -> None:
        """A held price came from the source of the earlier interval."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(websocket_message(price(T1000, 0.25, estimate=False)), source="websocket")
        store.record(polling_response(price(T1005, 0.40, estimate=True)), source="polling")

        assert store.view(WHILE_HOLDING).source == "websocket"


class TestRetention:
    """Old intervals are discarded explicitly."""

    def test_discarded_intervals_can_no_longer_be_held(self) -> None:
        """After discarding 10:00 there is nothing to hold for 10:05."""
        store = PriceStore(FIVE_MINUTES, hold=HOLD_FOR_45S)
        store.record(
            polling_response(price(T1000, 0.25, estimate=False), price(T1005, 0.40, estimate=True)),
            source="polling",
        )

        store.discard_before(T1005)

        assert ATTR_PER_KWH not in general_at(store, WHILE_HOLDING)


class TestConfirmsInterval:
    """A response confirms an interval only when every channel reporting a current interval is confirmed for it."""

    def test_confirmed_response_for_interval_confirms_it(self) -> None:
        """A confirmed polling response for 10:05 confirms 10:05."""
        assert confirms_interval(polling_response(price(T1005, 0.30, estimate=False)), T1005)

    def test_late_confirmed_response_for_previous_interval_does_not_confirm_current(self) -> None:
        """A confirmed response for 10:00 that arrives after the boundary does not confirm 10:05."""
        assert not confirms_interval(polling_response(price(T1000, 0.25, estimate=False)), T1005)

    def test_every_channel_must_be_confirmed(self) -> None:
        """An estimated feed-in price leaves the interval unconfirmed."""
        response = {
            CHANNEL_GENERAL: price(T1005, 0.30, estimate=False),
            CHANNEL_FEED_IN: price(T1005, 0.10, estimate=True),
        }

        assert not confirms_interval(response, T1005)

    def test_channel_with_only_forecasts_does_not_block_confirmation(self) -> None:
        """A channel without a current interval has nothing to confirm, so polling it all interval would be wasted."""
        response: dict[str, ChannelData] = {
            CHANNEL_GENERAL: price(T1005, 0.30, estimate=False),
            CHANNEL_FEED_IN: {ATTR_FORECAST: [price(T1010, 0.10, estimate=True)]},
        }

        assert confirms_interval(response, T1005)

    def test_response_without_any_current_interval_confirms_nothing(self) -> None:
        """Forecasts alone never confirm an interval."""
        response: dict[str, ChannelData] = {CHANNEL_GENERAL: {ATTR_FORECAST: [price(T1010, 0.30, estimate=True)]}}

        assert not confirms_interval(response, T1005)

    def test_websocket_message_can_confirm_interval(self) -> None:
        """Confirmation does not depend on the source."""
        assert confirms_interval(websocket_message(price(T1005, 0.30, estimate=False)), T1005)
