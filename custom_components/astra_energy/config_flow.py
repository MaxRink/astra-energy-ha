"""Config flow for Astra Energy."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AstraApiError, AstraAuthError, AstraClient
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_BASE_URL,
    CONF_IMPORT_STATISTICS,
    CONF_POLL_INTERVAL,
    CONF_RECENT_REFRESH_HOURS,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_BASE_URL,
    DEFAULT_IMPORT_STATISTICS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RECENT_REFRESH_HOURS,
    DOMAIN,
    MAX_BACKFILL_DAYS,
    MAX_RECENT_REFRESH_HOURS,
    MIN_POLL_INTERVAL,
)


class CannotConnect(Exception):
    """Unable to connect to Astra."""


class InvalidAuth(Exception):
    """Invalid Astra authentication."""


async def _async_validate_input(hass, user_input: dict[str, Any]) -> None:
    """Validate Astra credentials by logging in through the Android API."""
    client = AstraClient(
        async_get_clientsession(hass),
        username=user_input[CONF_USERNAME],
        password=user_input[CONF_PASSWORD],
        base_url=user_input[CONF_BASE_URL],
    )
    try:
        await client.async_get_account_info()
    except AstraAuthError as err:
        raise InvalidAuth from err
    except AstraApiError as err:
        raise CannotConnect from err


def _data_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the shared config/reconfigure schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_BASE_URL, default=defaults.get(CONF_BASE_URL, DEFAULT_BASE_URL)): str,
            vol.Required(
                CONF_POLL_INTERVAL,
                default=defaults.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL)),
            vol.Required(
                CONF_BACKFILL_DAYS,
                default=defaults.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_BACKFILL_DAYS)),
            vol.Required(
                CONF_RECENT_REFRESH_HOURS,
                default=defaults.get(CONF_RECENT_REFRESH_HOURS, DEFAULT_RECENT_REFRESH_HOURS),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_RECENT_REFRESH_HOURS)),
            vol.Required(
                CONF_IMPORT_STATISTICS,
                default=defaults.get(CONF_IMPORT_STATISTICS, DEFAULT_IMPORT_STATISTICS),
            ): bool,
        }
    )


class AstraEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an Astra Energy config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_BASE_URL] = user_input[CONF_BASE_URL].rstrip("/")
            try:
                await _async_validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_USERNAME].strip().lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Astra Energy ({user_input[CONF_USERNAME]})",
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_BASE_URL: user_input[CONF_BASE_URL],
                    },
                    options={
                        CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL],
                        CONF_BACKFILL_DAYS: user_input[CONF_BACKFILL_DAYS],
                        CONF_RECENT_REFRESH_HOURS: user_input[CONF_RECENT_REFRESH_HOURS],
                        CONF_IMPORT_STATISTICS: user_input[CONF_IMPORT_STATISTICS],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema(),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> config_entries.ConfigFlowResult:
        """Handle reauthentication."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm(entry_data)

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm reauthentication credentials."""
        entry = self._reauth_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = dict(entry.data) | {
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await _async_validate_input(self.hass, merged)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=merged)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle reconfiguration from the UI."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        defaults = dict(entry.data) | dict(entry.options)
        defaults[CONF_PASSWORD] = ""
        if user_input is not None:
            merged = dict(entry.data) | {
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_BASE_URL: user_input[CONF_BASE_URL].rstrip("/"),
            }
            try:
                await _async_validate_input(self.hass, merged)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=merged,
                    options={
                        CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL],
                        CONF_BACKFILL_DAYS: user_input[CONF_BACKFILL_DAYS],
                        CONF_RECENT_REFRESH_HOURS: user_input[CONF_RECENT_REFRESH_HOURS],
                        CONF_IMPORT_STATISTICS: user_input[CONF_IMPORT_STATISTICS],
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_data_schema(defaults),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        return AstraEnergyOptionsFlow(config_entry)


class AstraEnergyOptionsFlow(config_entries.OptionsFlow):
    """Astra Energy options flow."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL)),
                    vol.Required(
                        CONF_BACKFILL_DAYS,
                        default=self.config_entry.options.get(
                            CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_BACKFILL_DAYS)),
                    vol.Required(
                        CONF_RECENT_REFRESH_HOURS,
                        default=self.config_entry.options.get(
                            CONF_RECENT_REFRESH_HOURS, DEFAULT_RECENT_REFRESH_HOURS
                        ),
                    ): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=MAX_RECENT_REFRESH_HOURS)
                    ),
                    vol.Required(
                        CONF_IMPORT_STATISTICS,
                        default=self.config_entry.options.get(
                            CONF_IMPORT_STATISTICS, DEFAULT_IMPORT_STATISTICS
                        ),
                    ): bool,
                }
            ),
        )
