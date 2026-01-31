"""Persistence layer for CDF polling observations."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from homeassistant.helpers.storage import Store

from .cdf_cold_start import COLD_START_OBSERVATIONS
from .cdf_polling import IntervalObservation
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1


class CDFStorageData(TypedDict):
    """Stored data format for CDF observations."""

    observations: list[IntervalObservation]


class CDFObservationStore:
    """Handles persistence of CDF polling observations using Home Assistant storage.

    This is the single source of truth for observations. When no storage exists,
    cold start observations are returned to provide a reasonable starting point.
    """

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

    async def async_load(self) -> list[IntervalObservation]:
        """Load observations from storage, or cold start if none exist.

        Returns:
            List of observations from storage, or cold start observations if
            no storage exists.

        """
        data = await self._store.async_load()
        if data is None:
            return list(COLD_START_OBSERVATIONS)
        return data.get("observations", list(COLD_START_OBSERVATIONS))

    async def async_save(self, observations: list[IntervalObservation]) -> None:
        """Save observations to storage.

        Args:
            observations: List of interval observations to persist

        """
        data: CDFStorageData = {"observations": observations}
        await self._store.async_save(data)
