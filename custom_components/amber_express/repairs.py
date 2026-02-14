"""Repairs support for Amber Express."""

from __future__ import annotations

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
import voluptuous as vol

from .const import CONF_PRICING_MODE, CONF_SITE_NAME, DOMAIN, PRICING_MODE_APP

LEGACY_PRICING_MODE_ALL = "all"
ISSUE_ID_LEGACY_PRICING_MODE_ALL = "legacy_pricing_mode_all"


def issue_id_for_legacy_pricing_mode_all(subentry_id: str) -> str:
    """Build issue ID for a legacy both pricing mode subentry."""
    return f"{ISSUE_ID_LEGACY_PRICING_MODE_ALL}_{subentry_id}"


@callback
def async_create_legacy_pricing_mode_all_issue(
    hass: HomeAssistant,
    entry_id: str,
    subentry_id: str,
    site_name: str,
) -> None:
    """Create a blocking repair issue for legacy both pricing mode."""
    ir.async_create_issue(
        hass=hass,
        domain=DOMAIN,
        issue_id=issue_id_for_legacy_pricing_mode_all(subentry_id),
        data={"entry_id": entry_id, "subentry_id": subentry_id},
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_ID_LEGACY_PRICING_MODE_ALL,
        translation_placeholders={"site_name": site_name},
    )


@callback
def async_delete_legacy_pricing_mode_all_issue(hass: HomeAssistant, subentry_id: str) -> None:
    """Delete the legacy both pricing mode repair issue for a subentry."""
    ir.async_delete_issue(
        hass=hass,
        domain=DOMAIN,
        issue_id=issue_id_for_legacy_pricing_mode_all(subentry_id),
    )


class LegacyPricingModeAllRepairFlow(RepairsFlow):
    """Repair flow for migrating legacy both pricing mode."""

    def __init__(self, entry_id: str, subentry_id: str) -> None:
        """Initialize migration flow."""
        self._entry_id = entry_id
        self._subentry_id = subentry_id

    async def async_step_init(self, _: dict[str, str] | None = None) -> data_entry_flow.FlowResult:
        """Handle the first step of a fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> data_entry_flow.FlowResult:
        """Handle the confirm step of a fix flow."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            raise RuntimeError
        subentry = entry.subentries[self._subentry_id]

        if user_input is not None:
            if subentry.data.get(CONF_PRICING_MODE) == LEGACY_PRICING_MODE_ALL:
                updated_data = dict(subentry.data)
                updated_data[CONF_PRICING_MODE] = PRICING_MODE_APP
                self.hass.config_entries.async_update_subentry(entry, subentry, data=updated_data)

            async_delete_legacy_pricing_mode_all_issue(self.hass, self._subentry_id)
            return self.async_create_entry(data={})

        site_name = subentry.data.get(CONF_SITE_NAME, subentry.title)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"site_name": site_name},
        )


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repair flow for legacy pricing mode migration."""
    if not issue_id.startswith(f"{ISSUE_ID_LEGACY_PRICING_MODE_ALL}_"):
        raise ValueError
    if data is None:
        raise ValueError

    entry_id = data["entry_id"]
    subentry_id = data["subentry_id"]
    if not isinstance(entry_id, str) or not isinstance(subentry_id, str):
        raise TypeError

    return LegacyPricingModeAllRepairFlow(entry_id=entry_id, subentry_id=subentry_id)
