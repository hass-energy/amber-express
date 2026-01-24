"""Config flow for Amber Express integration."""

from __future__ import annotations

import logging
from typing import Any

import amberelectric
from amberelectric.api import amber_api
from amberelectric.configuration import Configuration
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .const import (
    CONF_API_TOKEN,
    CONF_ENABLE_CONTROLLED_LOAD,
    CONF_ENABLE_FEED_IN,
    CONF_ENABLE_GENERAL,
    CONF_ENABLE_WEBSOCKET,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_WAIT_FOR_CONFIRMED,
    DEFAULT_ENABLE_CONTROLLED_LOAD,
    DEFAULT_ENABLE_FEED_IN,
    DEFAULT_ENABLE_GENERAL,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_PRICING_MODE,
    DEFAULT_WAIT_FOR_CONFIRMED,
    DOMAIN,
    PRICING_MODE_AEMO,
    PRICING_MODE_APP,
)

_LOGGER = logging.getLogger(__name__)

# HTTP status codes
HTTP_FORBIDDEN = 403


class InvalidAuthError(HomeAssistantError):
    """Error to indicate invalid authentication."""


class NoSitesFoundError(HomeAssistantError):
    """Error to indicate no sites found for the account."""


async def validate_api_token(hass: HomeAssistant, api_token: str) -> list[dict[str, Any]]:
    """Validate the API token and return available sites."""
    configuration = Configuration(access_token=api_token)
    api = amber_api.AmberApi(amberelectric.ApiClient(configuration))

    try:
        sites = await hass.async_add_executor_job(api.get_sites)
    except amberelectric.ApiException as err:
        if err.status == HTTP_FORBIDDEN:
            raise InvalidAuthError from err
        raise

    if not sites:
        raise NoSitesFoundError

    # Convert sites to a list of dicts for easier handling
    site_list = []
    for site in sites:
        # Extract full channel info including tariff codes
        channels_info = []
        for ch in site.channels or []:
            channel_type = ch.type.value if hasattr(ch.type, "value") else str(ch.type)
            channels_info.append(
                {
                    "identifier": getattr(ch, "identifier", None),
                    "type": channel_type,
                    "tariff": getattr(ch, "tariff", None),
                }
            )

        site_list.append(
            {
                "id": site.id,
                "nmi": site.nmi,
                "status": site.status.value if hasattr(site.status, "value") else str(site.status),
                "network": getattr(site, "network", None),
                "channels": channels_info,
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:  # noqa: ARG004
        """Get the options flow for this handler."""
        return AmberElectricLiveOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step - API token entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._sites = await validate_api_token(self.hass, user_input[CONF_API_TOKEN])
                self._api_token = user_input[CONF_API_TOKEN]
                return await self.async_step_site()
            except InvalidAuthError:
                errors["base"] = "invalid_auth"
            except NoSitesFoundError:
                errors["base"] = "no_sites"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_TOKEN): str,
                }
            ),
            errors=errors,
            description_placeholders={"api_url": "https://app.amber.com.au/developers/"},
        )

    async def async_step_site(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the site selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            site_id = user_input[CONF_SITE_ID]

            # Check if this site is already configured
            await self.async_set_unique_id(site_id)
            self._abort_if_unique_id_configured()

            # Find the selected site to get channel/network info
            selected_site = next((s for s in self._sites if s["id"] == site_id), None)
            site_name = user_input.get(CONF_SITE_NAME) or site_id

            # Store channel and network info for the tariff sensor
            site_data: dict[str, Any] = {
                CONF_API_TOKEN: self._api_token,
                CONF_SITE_ID: site_id,
                CONF_SITE_NAME: site_name,
            }
            if selected_site:
                site_data["network"] = selected_site.get("network")
                site_data["nmi"] = selected_site.get("nmi")
                site_data["channels"] = selected_site.get("channels", [])

            return self.async_create_entry(
                title=site_name,
                data=site_data,
                options={
                    CONF_PRICING_MODE: DEFAULT_PRICING_MODE,
                    CONF_ENABLE_GENERAL: DEFAULT_ENABLE_GENERAL,
                    CONF_ENABLE_FEED_IN: DEFAULT_ENABLE_FEED_IN,
                    CONF_ENABLE_CONTROLLED_LOAD: DEFAULT_ENABLE_CONTROLLED_LOAD,
                    CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
                    CONF_WAIT_FOR_CONFIRMED: DEFAULT_WAIT_FOR_CONFIRMED,
                },
            )

        # Build site selection dropdown
        site_options = {}
        for site in self._sites:
            label = f"{site['nmi']} ({site['status']})"
            site_options[site["id"]] = label

        return self.async_show_form(
            step_id="site",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SITE_ID): vol.In(site_options),
                    vol.Optional(CONF_SITE_NAME): str,
                }
            ),
            errors=errors,
        )


class AmberElectricLiveOptionsFlow(OptionsFlow):
    """Handle options flow for Amber Express."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PRICING_MODE,
                        default=options.get(CONF_PRICING_MODE, DEFAULT_PRICING_MODE),
                    ): vol.In(
                        {
                            PRICING_MODE_AEMO: "AEMO (per_kwh - includes network tariffs)",
                            PRICING_MODE_APP: "APP (advanced_price_predicted - Amber's prediction)",
                        }
                    ),
                    vol.Required(
                        CONF_ENABLE_GENERAL,
                        default=options.get(CONF_ENABLE_GENERAL, DEFAULT_ENABLE_GENERAL),
                    ): bool,
                    vol.Required(
                        CONF_ENABLE_FEED_IN,
                        default=options.get(CONF_ENABLE_FEED_IN, DEFAULT_ENABLE_FEED_IN),
                    ): bool,
                    vol.Required(
                        CONF_ENABLE_CONTROLLED_LOAD,
                        default=options.get(CONF_ENABLE_CONTROLLED_LOAD, DEFAULT_ENABLE_CONTROLLED_LOAD),
                    ): bool,
                    vol.Required(
                        CONF_ENABLE_WEBSOCKET,
                        default=options.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET),
                    ): bool,
                    vol.Required(
                        CONF_WAIT_FOR_CONFIRMED,
                        default=options.get(CONF_WAIT_FOR_CONFIRMED, DEFAULT_WAIT_FOR_CONFIRMED),
                    ): bool,
                }
            ),
        )
