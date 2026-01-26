"""Utility functions for Amber Express."""

PRICE_DECIMAL_PLACES = 2


def cents_to_dollars(cents: float | None) -> float | None:
    """Convert cents to dollars, rounded to avoid floating point artifacts."""
    if cents is None:
        return None
    return round(cents / 100, PRICE_DECIMAL_PLACES)
