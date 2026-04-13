"""Tests for utility helpers."""

from custom_components.amber_express.utils import cents_to_dollars, to_local_iso_minute


def test_cents_to_dollars_none_returns_none() -> None:
    """None cents maps to None dollars."""
    assert cents_to_dollars(None) is None


def test_to_local_iso_minute_unparseable_returns_original() -> None:
    """When the string is not a valid datetime, it is returned unchanged."""
    assert to_local_iso_minute("not-a-valid-timestamp") == "not-a-valid-timestamp"
