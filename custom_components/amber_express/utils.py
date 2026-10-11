"""Utility functions for Amber Express."""

from datetime import timedelta
from http import HTTPStatus

from homeassistant.util import dt as dt_util

# Amber prices are 5dp in cents, +2 for the cents->dollars conversion. Rounding to
# this precision is lossless for real values while removing float division artifacts.
AMBER_PRICE_DECIMAL_PLACES = 7


def cents_to_dollars(cents: float | None) -> float | None:
    """Convert cents to dollars at Amber's full price precision.

    Rounds to the genuine precision ceiling to strip float division artifacts
    without losing data.
    """
    if cents is None:
        return None
    return round(cents / 100, AMBER_PRICE_DECIMAL_PLACES)


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


def get_http_status_label(status_code: int) -> str:
    """Get human-readable label for HTTP status code."""
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Unknown Error"
