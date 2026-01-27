"""Persistence layer for CDF polling observations."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from homeassistant.helpers.storage import Store

from .cdf_polling import IntervalObservation
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1


class CDFStorageData(TypedDict):
    """Stored data format for CDF observations."""

    observations: list[IntervalObservation]


class CDFObservationStore:
    """Handles persistence of CDF polling observations using Home Assistant storage."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store.

        Args:
            hass: Home Assistant instance
            entry_id: Config entry ID for unique storage key

        """
        self._store: Store[CDFStorageData] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.cdf_observations.{entry_id}",
        )

    async def async_load(self) -> list[IntervalObservation] | None:
        """Load observations from storage.

        Returns:
            List of observations if found, None if no stored data.

        """
        data = await self._store.async_load()
        if data is None:
            return None
        return data.get("observations")

    async def async_save(self, observations: list[IntervalObservation]) -> None:
        """Save observations to storage.

        Args:
            observations: List of interval observations to persist

        """
        data: CDFStorageData = {"observations": observations}
        await self._store.async_save(data)
