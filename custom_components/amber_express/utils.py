"""Utility functions for Amber Express."""

from datetime import timedelta

from homeassistant.util import dt as dt_util

PRICE_DECIMAL_PLACES = 4


def cents_to_dollars(cents: float | None) -> float | None:
    """Convert cents to dollars, rounded to avoid floating point artifacts."""
    if cents is None:
        return None
    return round(cents / 100, PRICE_DECIMAL_PLACES)


def to_local_iso_minute(iso_string: str | None) -> str | None:
    """Convert an ISO timestamp to local timezone, rounded to the nearest minute."""
    if iso_string is None:
        return None
    dt = dt_util.parse_datetime(iso_string)
    if dt is None:
        return iso_string
    local_dt = dt_util.as_local(dt)
    rounded = (local_dt + timedelta(seconds=30)).replace(second=0, microsecond=0)
    return rounded.isoformat()
