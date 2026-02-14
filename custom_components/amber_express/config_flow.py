"""Config flow for Amber Express integration."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
    UnknownSubEntry,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
from homeassistant.helpers.translation import async_get_translations
import voluptuous as vol

from .api_client import AmberApiClient, AmberApiError
from .api_client import RateLimitedError as ApiRateLimitedError
from .const import (
    API_DEVELOPER_URL,
    CONF_API_TOKEN,
    CONF_CONFIRMATION_TIMEOUT,
    CONF_DEMAND_WINDOW_PRICE,
    CONF_ENABLE_WEBSOCKET,
    CONF_FORECAST_INTERVALS,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DEFAULT_CONFIRMATION_TIMEOUT,
    DEFAULT_DEMAND_WINDOW_PRICE,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_FORECAST_INTERVALS,
    DEFAULT_PRICING_MODE,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
    MAX_FORECAST_INTERVALS,
    PRICING_MODE_AEMO,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from .rate_limiter import ExponentialBackoffRateLimiter

_LOGGER = logging.getLogger(__name__)

# HTTP status codes
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429


class InvalidAuthError(HomeAssistantError):
    """Error to indicate invalid authentication."""


class NoSitesFoundError(HomeAssistantError):
    """Error to indicate no sites found for the account."""


class RateLimitedError(HomeAssistantError):
    """Error to indicate API rate limit exceeded."""


async def validate_api_token(hass: HomeAssistant, api_token: str) -> list[dict[str, Any]]:
    """Validate the API token and return available sites."""
    # Use a temporary rate limiter (not shared with coordinator)
    rate_limiter = ExponentialBackoffRateLimiter()
    client = AmberApiClient(hass, api_token, rate_limiter)

    try:
        sites = await client.fetch_sites()
    except ApiRateLimitedError as err:
        raise RateLimitedError from err
    except AmberApiError as err:
        if err.status == HTTP_FORBIDDEN:
            raise InvalidAuthError from err
        msg = f"Failed to fetch sites: {err}"
        raise HomeAssistantError(msg) from err

    if not sites:
        raise NoSitesFoundError

    # Convert sites to a list of dicts for easier handling
    site_list = []
    for site in sites:
        # Extract full channel info including tariff codes
        channels_info = [
            {
                "identifier": ch.identifier,
                "type": ch.type.value,
                "tariff": ch.tariff,
            }
            for ch in site.channels
        ]

        site_list.append(
            {
                "id": site.id,
                "nmi": site.nmi,
                "status": site.status.value,
                "network": site.network,
                "channels": channels_info,
                "active_from": str(site.active_from) if site.active_from else None,
                "interval_length": site.interval_length,
            }
        )

    return site_list


class AmberElectricLiveConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Amber Express."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api_token: str | None = None
        self._sites: list[dict] = []
        self._selected_sites: list[dict[str, Any]] = []
        self._current_site_index: int = 0
        self._site_names: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:  # noqa: ARG004
        """Get the options flow for this handler."""
        # Main entry has no options - options are on subentries
        return AmberElectricLiveOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,  # noqa: ARG003
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types supported by this integration."""
        return {SUBENTRY_TYPE_SITE: SiteSubentryFlowHandler}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step - API token entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                all_sites = await validate_api_token(self.hass, user_input[CONF_API_TOKEN])
                # Filter to only active sites
                active_sites = [s for s in all_sites if s.get("status") == "active"]

                if not active_sites:
                    errors["base"] = "no_sites"
                else:
                    self._sites = active_sites
                    self._api_token = user_input[CONF_API_TOKEN]

                    # Check if we already have an entry with this token
                    existing_entries = self._async_current_entries()
                    for entry in existing_entries:
                        if entry.data.get(CONF_API_TOKEN) == self._api_token:
                            # Token already configured - abort
                            return self.async_abort(reason="already_configured")

                    if len(self._sites) == 1:
                        # Single site - pre-select and go to naming
                        self._selected_sites = self._sites
                        return await self.async_step_name_sites()
                    # Multiple sites - let user choose
                    return await self.async_step_select_sites()
            except InvalidAuthError:
                errors["base"] = "invalid_auth"
            except NoSitesFoundError:
                errors["base"] = "no_sites"
            except RateLimitedError:
                errors["base"] = "rate_limited"
            except AbortFlow:
                raise
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # Pre-fill the token if user already entered one (for retry after error)
        default_token = user_input.get(CONF_API_TOKEN, "") if user_input else ""

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_TOKEN, default=default_token): str,
                }
            ),
            errors=errors,
            description_placeholders={"api_url": API_DEVELOPER_URL},
        )

    def _get_site_dropdown_label(self, site: dict[str, Any]) -> str:
        """Build a short label for site dropdown selection."""
        nmi = site.get("nmi", "Unknown")
        network = site.get("network", "Unknown")
        return f"{nmi} ({network})"

    async def async_step_select_sites(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle site selection step for multiple sites."""
        if user_input is not None:
            selected_ids = user_input.get("selected_sites", [])
            if not selected_ids:
                return self.async_show_form(
                    step_id="select_sites",
                    data_schema=self._get_site_selection_schema(),
                    errors={"base": "no_sites_selected"},
                )
            self._selected_sites = [s for s in self._sites if s["id"] in selected_ids]
            return await self.async_step_name_sites()

        return self.async_show_form(
            step_id="select_sites",
            data_schema=self._get_site_selection_schema(),
        )

    def _get_site_selection_schema(self) -> vol.Schema:
        """Build schema for site selection with checkboxes."""
        site_options: list[dict[str, str]] = [
            {"value": site["id"], "label": self._get_site_dropdown_label(site)} for site in self._sites
        ]
        return vol.Schema(
            {
                vol.Required("selected_sites"): SelectSelector(
                    SelectSelectorConfig(
                        options=site_options,  # type: ignore[arg-type]
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

    async def async_step_name_sites(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle naming of selected sites one by one."""
        if user_input is not None:
            # Store the name for the current site
            current_site = self._selected_sites[self._current_site_index]
            self._site_names[current_site["id"]] = user_input[CONF_SITE_NAME]

            # Move to next site or finish
            self._current_site_index += 1
            if self._current_site_index >= len(self._selected_sites):
                # All sites named - create the entry
                return await self._create_entry_with_subentries()
            # Show form for next site

        # Get current site to name
        current_site = self._selected_sites[self._current_site_index]
        suggested_name = await self._get_suggested_site_name(self._current_site_index)

        return self.async_show_form(
            step_id="name_sites",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SITE_NAME, default=suggested_name): str,
                }
            ),
            description_placeholders=self._get_site_placeholders(current_site),
        )

    def _get_site_placeholders(self, site: dict[str, Any]) -> dict[str, str]:
        """Build description placeholders for a site."""
        interval = site.get("interval_length")
        active_from = site.get("active_from")

        return {
            "site_id": site.get("id", "Unknown"),
            "nmi": site.get("nmi", "Unknown"),
            "network": site.get("network", "Unknown"),
            "interval": f"{int(interval)} minutes" if interval else "Unknown",
            "active_from": str(active_from) if active_from else "Unknown",
        }

    async def _get_suggested_site_name(self, site_index: int) -> str:
        """Get translated suggested site name."""
        translations = await async_get_translations(self.hass, self.hass.config.language, "config", [DOMAIN])
        key = f"component.{DOMAIN}.config.step.name_sites.suggested_site_name"
        base_name = translations.get(key, "Home")
        # If multiple sites, add suffix for subsequent sites
        if len(self._selected_sites) > 1:
            return f"{base_name} {site_index + 1}" if site_index > 0 else base_name
        return base_name

    async def _create_entry_with_subentries(self) -> ConfigFlowResult:
        """Create the main config entry with site subentries."""
        # Use a unique ID based on API token hash (first 8 chars)
        token_hash = str(hash(self._api_token))[:8]
        await self.async_set_unique_id(f"amber_{token_hash}")
        self._abort_if_unique_id_configured()

        # Build subentries for each selected site
        subentries = []
        for site in self._selected_sites:
            site_id = site["id"]
            site_name = self._site_names.get(site_id, "Amber Site")
            subentries.append(
                {
                    "data": {
                        CONF_SITE_ID: site_id,
                        CONF_SITE_NAME: site_name,
                        "nmi": site.get("nmi"),
                        "network": site.get("network"),
                        "channels": site.get("channels", []),
                        # Default options for the site
                        CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
                        CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
                        CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
                        CONF_CONFIRMATION_TIMEOUT: DEFAULT_CONFIRMATION_TIMEOUT,
                        CONF_FORECAST_INTERVALS: DEFAULT_FORECAST_INTERVALS,
                    },
                    "subentry_type": SUBENTRY_TYPE_SITE,
                    "title": site_name,
                    "unique_id": site_id,
                }
            )

        # Create the main entry with API token only
        return self.async_create_entry(
            title="Amber Electric",
            data={
                CONF_API_TOKEN: self._api_token,
            },
            subentries=subentries,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle reconfiguring the hub (API token)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            new_token = user_input.get(CONF_API_TOKEN, "").strip()

            # If empty, keep existing token
            if not new_token:
                new_token = entry.data[CONF_API_TOKEN]

            # Validate and fetch sites
            try:
                sites = await validate_api_token(self.hass, new_token)
                active_sites = [s for s in sites if s.get("status") == "active"]

                if not active_sites:
                    errors["base"] = "no_sites"
                else:
                    # Store for next step
                    self._api_token = new_token
                    self._available_sites = active_sites
                    self._reconfig_entry = entry
                    return await self.async_step_reconfigure_sites()

            except InvalidAuthError:
                errors[CONF_API_TOKEN] = "invalid_auth"
            except RateLimitedError:
                errors["base"] = "rate_limited"
            except NoSitesFoundError:
                errors["base"] = "no_sites"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_API_TOKEN, default=""): str,
                }
            ),
            errors=errors,
            description_placeholders={"api_url": API_DEVELOPER_URL},
        )

    async def async_step_reconfigure_sites(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle site selection during reconfigure."""
        entry = self._reconfig_entry
        errors: dict[str, str] = {}

        # Get currently configured site IDs
        current_site_ids = {
            subentry.data.get(CONF_SITE_ID)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_SITE
        }

        if user_input is not None:
            selected_ids = user_input.get("selected_sites", [])
            if not selected_ids:
                errors["base"] = "no_sites_selected"
            else:
                # Store selected sites for naming
                self._selected_sites = [s for s in self._available_sites if s["id"] in selected_ids]
                # Track which are new (need naming)
                self._new_site_ids = {s["id"] for s in self._selected_sites if s["id"] not in current_site_ids}
                self._site_names = {}
                self._current_site_index = 0

                # Copy names for existing sites
                for subentry in entry.subentries.values():
                    site_id = subentry.data.get(CONF_SITE_ID)
                    if site_id is not None and site_id in selected_ids:
                        self._site_names[site_id] = subentry.data.get(CONF_SITE_NAME, subentry.title)

                return await self.async_step_reconfigure_name_sites()

        # Build site options
        site_options = [
            {"value": site["id"], "label": f"{site.get('nmi', 'Unknown')} ({site.get('network', 'Unknown')})"}
            for site in self._available_sites
        ]

        return self.async_show_form(
            step_id="reconfigure_sites",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "selected_sites",
                        default=[s for s in current_site_ids if s is not None],
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=site_options,  # type: ignore[arg-type]
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_name_sites(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle naming new sites during reconfigure."""
        # Find next new site that needs naming
        while self._current_site_index < len(self._selected_sites):
            current_site = self._selected_sites[self._current_site_index]
            site_id = current_site["id"]

            # Skip if already named (existing site)
            if site_id in self._site_names:
                self._current_site_index += 1
                continue

            # Handle user input for this site
            if user_input is not None:
                self._site_names[site_id] = user_input[CONF_SITE_NAME]
                self._current_site_index += 1
                user_input = None
                continue

            # Show form for this new site
            suggested_name = await self._get_suggested_site_name(
                len([s for s in self._selected_sites[: self._current_site_index] if s["id"] in self._new_site_ids])
            )

            return self.async_show_form(
                step_id="reconfigure_name_sites",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_SITE_NAME, default=suggested_name): str,
                    }
                ),
                description_placeholders=self._get_site_placeholders(current_site),
            )

        # All sites named - apply changes
        return await self._apply_reconfigure_changes()

    async def _apply_reconfigure_changes(self) -> ConfigFlowResult:
        """Apply reconfigure changes to entry and subentries."""
        entry = self._reconfig_entry
        selected_site_ids = {s["id"] for s in self._selected_sites}

        # Map existing subentries by site_id
        existing_subentries: dict[str, ConfigSubentry] = {}
        for subentry in entry.subentries.values():
            if subentry.subentry_type == SUBENTRY_TYPE_SITE:
                site_id = subentry.data.get(CONF_SITE_ID)
                if site_id is not None:
                    existing_subentries[site_id] = subentry

        # Remove subentries for sites that are no longer selected
        for site_id, subentry in existing_subentries.items():
            if site_id not in selected_site_ids:
                self.hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)

        # Add or update subentries for selected sites
        for site in self._selected_sites:
            site_id = site["id"]
            site_name = self._site_names.get(site_id, "Amber Site")

            if site_id in existing_subentries:
                # Update existing subentry with new name if changed
                subentry = existing_subentries[site_id]
                if subentry.data.get(CONF_SITE_NAME) != site_name:
                    updated_data = dict(subentry.data)
                    updated_data[CONF_SITE_NAME] = site_name
                    self.hass.config_entries.async_update_subentry(
                        entry,
                        subentry,
                        data=updated_data,
                        title=site_name,
                    )
            else:
                # Create new subentry
                subentry_data: dict[str, Any] = {
                    CONF_SITE_ID: site_id,
                    CONF_SITE_NAME: site_name,
                    "nmi": site.get("nmi"),
                    "network": site.get("network"),
                    "channels": site.get("channels", []),
                    CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
                    CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
                    CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
                    CONF_CONFIRMATION_TIMEOUT: DEFAULT_CONFIRMATION_TIMEOUT,
                    CONF_FORECAST_INTERVALS: DEFAULT_FORECAST_INTERVALS,
                }
                self.hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(
                        data=MappingProxyType(subentry_data),
                        subentry_type=SUBENTRY_TYPE_SITE,
                        title=site_name,
                        unique_id=site_id,
                    ),
                )

        # Update entry data and reload
        return self.async_update_reload_and_abort(
            entry,
            data={CONF_API_TOKEN: self._api_token},
        )


class SiteSubentryFlowHandler(ConfigSubentryFlow):
    """Handle site subentry flows for adding/reconfiguring sites."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle adding a new site."""
        errors: dict[str, str] = {}
        entry = self._get_entry()
        api_token = entry.data[CONF_API_TOKEN]

        # Get sites that are not already configured
        try:
            all_sites = await validate_api_token(self.hass, api_token)
            active_sites = [s for s in all_sites if s.get("status") == "active"]

            # Filter out already-configured sites
            configured_site_ids = {subentry.data.get(CONF_SITE_ID) for subentry in entry.subentries.values()}
            available_sites = [s for s in active_sites if s["id"] not in configured_site_ids]

            if not available_sites:
                return self.async_abort(reason="no_sites_available")

        except InvalidAuthError:
            return self.async_abort(reason="invalid_auth")
        except RateLimitedError:
            return self.async_abort(reason="rate_limited")
        except NoSitesFoundError:
            return self.async_abort(reason="no_sites")

        if user_input is not None:
            site_id = user_input[CONF_SITE_ID]
            site_name = user_input[CONF_SITE_NAME]

            # Find the selected site
            site = next((s for s in available_sites if s["id"] == site_id), None)
            if site:
                return self.async_create_entry(
                    title=site_name,
                    data={
                        CONF_SITE_ID: site_id,
                        CONF_SITE_NAME: site_name,
                        "nmi": site.get("nmi"),
                        "network": site.get("network"),
                        "channels": site.get("channels", []),
                        CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
                        CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
                        CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
                        CONF_CONFIRMATION_TIMEOUT: DEFAULT_CONFIRMATION_TIMEOUT,
                        CONF_FORECAST_INTERVALS: DEFAULT_FORECAST_INTERVALS,
                    },
                    unique_id=site_id,
                )

        # Build site selection options
        site_options = {
            site["id"]: f"{site.get('nmi', 'Unknown')} ({site.get('network', 'Unknown')})" for site in available_sites
        }

        # Get suggested name
        translations = await async_get_translations(self.hass, self.hass.config.language, "config_subentries", [DOMAIN])
        key = f"component.{DOMAIN}.config_subentries.{SUBENTRY_TYPE_SITE}.step.user.suggested_site_name"
        suggested_name = translations.get(key, "Home")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SITE_ID): vol.In(site_options),
                    vol.Required(CONF_SITE_NAME, default=suggested_name): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle reconfiguring an existing site."""
        subentry = self._get_reconfigure_subentry()
        current_data = dict(subentry.data)

        if user_input is not None:
            # Update the subentry with new data
            updated_data = {
                **current_data,
                CONF_SITE_NAME: user_input[CONF_SITE_NAME],
                CONF_PRICING_MODE: user_input[CONF_PRICING_MODE],
                CONF_ENABLE_WEBSOCKET: user_input[CONF_ENABLE_WEBSOCKET],
                CONF_WAIT_FOR_CONFIRMED: user_input[CONF_WAIT_FOR_CONFIRMED],
                CONF_CONFIRMATION_TIMEOUT: user_input[CONF_CONFIRMATION_TIMEOUT],
                CONF_FORECAST_INTERVALS: user_input[CONF_FORECAST_INTERVALS],
            }
            if CONF_DEMAND_WINDOW_PRICE in user_input:
                updated_data[CONF_DEMAND_WINDOW_PRICE] = user_input[CONF_DEMAND_WINDOW_PRICE]

            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_SITE_NAME],
                data=updated_data,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SITE_NAME,
                        default=current_data.get(CONF_SITE_NAME, subentry.title),
                    ): str,
                    vol.Required(
                        CONF_PRICING_MODE,
                        default=current_data.get(CONF_PRICING_MODE, DEFAULT_PRICING_MODE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": PRICING_MODE_APP, "label": "advanced_price_predicted"},
                                {"value": PRICING_MODE_AEMO, "label": "per_kwh"},
                            ],
                            translation_key="pricing_mode",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_ENABLE_WEBSOCKET,
                        default=current_data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET),
                    ): bool,
                    vol.Required(
                        CONF_WAIT_FOR_CONFIRMED,
                        default=current_data.get(CONF_WAIT_FOR_CONFIRMED, DEFAULT_WAIT_FOR_CONFIRMED),
                    ): bool,
                    vol.Required(
                        CONF_CONFIRMATION_TIMEOUT,
                        default=current_data.get(CONF_CONFIRMATION_TIMEOUT, DEFAULT_CONFIRMATION_TIMEOUT),
                    ): vol.Coerce(int),
                    vol.Required(
                        CONF_FORECAST_INTERVALS,
                        default=current_data.get(CONF_FORECAST_INTERVALS, DEFAULT_FORECAST_INTERVALS),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_FORECAST_INTERVALS)),
                    vol.Optional(
                        CONF_DEMAND_WINDOW_PRICE,
                        default=current_data.get(CONF_DEMAND_WINDOW_PRICE, DEFAULT_DEMAND_WINDOW_PRICE),
                    ): vol.Coerce(float),
                }
            ),
            description_placeholders={
                "site_id": current_data.get(CONF_SITE_ID, "Unknown"),
                "nmi": current_data.get("nmi", "Unknown"),
                "network": current_data.get("network", "Unknown"),
            },
        )

    def _get_subentry(self) -> ConfigSubentry | None:
        """Get the subentry being reconfigured, or None for new entries."""
        try:
            return self._get_reconfigure_subentry()
        except (ValueError, UnknownSubEntry):
            return None


class AmberElectricLiveOptionsFlow(OptionsFlow):
    """Handle options flow for Amber Express main entry.

    Allows renaming the hub. Site-specific options are on subentries.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Allow renaming the hub and show info about site options."""
        if user_input is not None:
            # Update the entry title if changed
            new_title = user_input.get("title", self.config_entry.title)
            if new_title != self.config_entry.title:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=new_title,
                )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("title", default=self.config_entry.title): str,
                }
            ),
            description_placeholders={},
        )
