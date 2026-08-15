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
    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
    CONF_BACKFILL_DAYS,
    CONF_BASE_URL,
    CONF_BROWSER_PROXY_ENABLED,
    CONF_BROWSER_PROXY_TOKEN,
    CONF_BROWSER_PROXY_URL,
    CONF_CACHE_INTERVAL_PAYLOADS,
    CONF_GRID_PRICE_NET,
    CONF_HISTORY_GRANULARITY,
    CONF_IMPORT_STATISTICS,
    CONF_MAX_INTERVAL_AVERAGE_KW,
    CONF_POLL_INTERVAL,
    CONF_RECENT_REFRESH_HOURS,
    CONF_SMOOTH_INTERVAL_ANOMALIES,
    CONF_SMOOTHING_LOOKAROUND_DAYS,
    CONF_SOLAR_PRICE_NET,
    CONF_TAX_RATE,
    CONF_WEB_BASE_URL,
    CONF_WEB_COOKIE,
    CONF_WEB_FALLBACK_ENABLED,
    CONF_WEB_GRAPH_TOTAL_ID,
    CONF_WEB_SESSION_ID,
    DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_BASE_URL,
    DEFAULT_BROWSER_PROXY_ENABLED,
    DEFAULT_BROWSER_PROXY_TOKEN,
    DEFAULT_BROWSER_PROXY_URL,
    DEFAULT_CACHE_INTERVAL_PAYLOADS,
    DEFAULT_GRID_PRICE_NET,
    DEFAULT_HISTORY_GRANULARITY,
    DEFAULT_IMPORT_STATISTICS,
    DEFAULT_MAX_INTERVAL_AVERAGE_KW,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RECENT_REFRESH_HOURS,
    DEFAULT_SMOOTH_INTERVAL_ANOMALIES,
    DEFAULT_SMOOTHING_LOOKAROUND_DAYS,
    DEFAULT_SOLAR_PRICE_NET,
    DEFAULT_TAX_RATE,
    DEFAULT_WEB_BASE_URL,
    DEFAULT_WEB_FALLBACK_ENABLED,
    DEFAULT_WEB_GRAPH_TOTAL_ID,
    DOMAIN,
    HISTORY_GRANULARITIES,
    MAX_BACKFILL_DAYS,
    MAX_MAX_INTERVAL_AVERAGE_KW,
    MAX_ANOMALY_REDISTRIBUTION_WINDOW,
    MAX_PRICE_NET,
    MAX_RECENT_REFRESH_HOURS,
    MAX_SMOOTHING_LOOKAROUND_DAYS,
    MAX_TAX_RATE,
    MIN_MAX_INTERVAL_AVERAGE_KW,
    MIN_ANOMALY_REDISTRIBUTION_WINDOW,
    MIN_PRICE_NET,
    MIN_POLL_INTERVAL,
    MIN_SMOOTHING_LOOKAROUND_DAYS,
    MIN_TAX_RATE,
)


class CannotConnect(Exception):
    """Unable to connect to Astra."""


class InvalidAuth(Exception):
    """Invalid Astra authentication."""


def _number_box(
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    step: float | None = None,
    unit: str | None = None,
) -> vol.All:
    """Return a plain numeric validator for config flows."""
    validators: list[Any] = [vol.Coerce(float)]
    range_config: dict[str, float] = {}
    if min_value is not None:
        range_config["min"] = min_value
    if max_value is not None:
        range_config["max"] = max_value
    if range_config:
        validators.append(vol.Range(**range_config))
    return vol.All(*validators)


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



def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the schema for initial setup."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_BASE_URL, default=defaults.get(CONF_BASE_URL, DEFAULT_BASE_URL)): str,
        }
    )

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
            ): _number_box(min_value=MIN_POLL_INTERVAL, step=60, unit="s"),
            vol.Required(
                CONF_BACKFILL_DAYS,
                default=defaults.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS),
            ): _number_box(min_value=0, max_value=MAX_BACKFILL_DAYS, step=1, unit="d"),
            vol.Required(
                CONF_RECENT_REFRESH_HOURS,
                default=defaults.get(CONF_RECENT_REFRESH_HOURS, DEFAULT_RECENT_REFRESH_HOURS),
            ): _number_box(min_value=0, max_value=MAX_RECENT_REFRESH_HOURS, step=1, unit="h"),
            vol.Required(
                CONF_HISTORY_GRANULARITY,
                default=defaults.get(
                    CONF_HISTORY_GRANULARITY,
                    DEFAULT_HISTORY_GRANULARITY,
                ),
            ): vol.In(HISTORY_GRANULARITIES),
            vol.Required(
                CONF_IMPORT_STATISTICS,
                default=defaults.get(CONF_IMPORT_STATISTICS, DEFAULT_IMPORT_STATISTICS),
            ): bool,
            vol.Required(
                CONF_GRID_PRICE_NET,
                default=defaults.get(CONF_GRID_PRICE_NET, DEFAULT_GRID_PRICE_NET),
            ): _number_box(
                min_value=MIN_PRICE_NET,
                max_value=MAX_PRICE_NET,
                step=0.00001,
                unit="EUR/kWh",
            ),
            vol.Required(
                CONF_SOLAR_PRICE_NET,
                default=defaults.get(CONF_SOLAR_PRICE_NET, DEFAULT_SOLAR_PRICE_NET),
            ): _number_box(
                min_value=MIN_PRICE_NET,
                max_value=MAX_PRICE_NET,
                step=0.00001,
                unit="EUR/kWh",
            ),
            vol.Required(
                CONF_TAX_RATE,
                default=defaults.get(CONF_TAX_RATE, DEFAULT_TAX_RATE),
            ): _number_box(min_value=MIN_TAX_RATE, max_value=MAX_TAX_RATE, step=0.01),
            vol.Required(
                CONF_MAX_INTERVAL_AVERAGE_KW,
                default=defaults.get(CONF_MAX_INTERVAL_AVERAGE_KW, DEFAULT_MAX_INTERVAL_AVERAGE_KW),
            ): _number_box(
                min_value=MIN_MAX_INTERVAL_AVERAGE_KW,
                max_value=MAX_MAX_INTERVAL_AVERAGE_KW,
                step=0.1,
                unit="kW",
            ),
            vol.Required(
                CONF_SMOOTH_INTERVAL_ANOMALIES,
                default=defaults.get(
                    CONF_SMOOTH_INTERVAL_ANOMALIES, DEFAULT_SMOOTH_INTERVAL_ANOMALIES
                ),
            ): bool,
            vol.Required(
                CONF_ANOMALY_REDISTRIBUTION_WINDOW,
                default=defaults.get(
                    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
                    DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
                ),
            ): _number_box(
                min_value=MIN_ANOMALY_REDISTRIBUTION_WINDOW,
                max_value=MAX_ANOMALY_REDISTRIBUTION_WINDOW,
                step=1,
                unit="buckets",
            ),
            vol.Required(
                CONF_SMOOTHING_LOOKAROUND_DAYS,
                default=defaults.get(
                    CONF_SMOOTHING_LOOKAROUND_DAYS, DEFAULT_SMOOTHING_LOOKAROUND_DAYS
                ),
            ): _number_box(
                min_value=MIN_SMOOTHING_LOOKAROUND_DAYS,
                max_value=MAX_SMOOTHING_LOOKAROUND_DAYS,
                step=1,
                unit="d",
            ),
            vol.Required(
                CONF_CACHE_INTERVAL_PAYLOADS,
                default=defaults.get(CONF_CACHE_INTERVAL_PAYLOADS, DEFAULT_CACHE_INTERVAL_PAYLOADS),
            ): bool,
            vol.Required(
                CONF_WEB_FALLBACK_ENABLED,
                default=defaults.get(CONF_WEB_FALLBACK_ENABLED, DEFAULT_WEB_FALLBACK_ENABLED),
            ): bool,
            vol.Optional(
                CONF_WEB_BASE_URL,
                default=defaults.get(CONF_WEB_BASE_URL, DEFAULT_WEB_BASE_URL),
            ): str,
            vol.Optional(
                CONF_WEB_SESSION_ID,
                default=defaults.get(CONF_WEB_SESSION_ID, ""),
            ): str,
            vol.Optional(
                CONF_WEB_COOKIE,
                default=defaults.get(CONF_WEB_COOKIE, ""),
            ): str,
            vol.Optional(
                CONF_WEB_GRAPH_TOTAL_ID,
                default=defaults.get(CONF_WEB_GRAPH_TOTAL_ID, DEFAULT_WEB_GRAPH_TOTAL_ID),
            ): str,
            vol.Required(
                CONF_BROWSER_PROXY_ENABLED,
                default=defaults.get(
                    CONF_BROWSER_PROXY_ENABLED, DEFAULT_BROWSER_PROXY_ENABLED
                ),
            ): bool,
            vol.Optional(
                CONF_BROWSER_PROXY_URL,
                default=defaults.get(CONF_BROWSER_PROXY_URL, DEFAULT_BROWSER_PROXY_URL),
            ): str,
            vol.Optional(
                CONF_BROWSER_PROXY_TOKEN,
                default=defaults.get(
                    CONF_BROWSER_PROXY_TOKEN, DEFAULT_BROWSER_PROXY_TOKEN
                ),
            ): str,
        }
    )


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the options-only schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_POLL_INTERVAL,
                default=defaults.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): _number_box(min_value=MIN_POLL_INTERVAL, step=60, unit="s"),
            vol.Required(
                CONF_BACKFILL_DAYS,
                default=defaults.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS),
            ): _number_box(min_value=0, max_value=MAX_BACKFILL_DAYS, step=1, unit="d"),
            vol.Required(
                CONF_RECENT_REFRESH_HOURS,
                default=defaults.get(CONF_RECENT_REFRESH_HOURS, DEFAULT_RECENT_REFRESH_HOURS),
            ): _number_box(min_value=0, max_value=MAX_RECENT_REFRESH_HOURS, step=1, unit="h"),
            vol.Required(
                CONF_HISTORY_GRANULARITY,
                default=defaults.get(
                    CONF_HISTORY_GRANULARITY,
                    DEFAULT_HISTORY_GRANULARITY,
                ),
            ): vol.In(HISTORY_GRANULARITIES),
            vol.Required(
                CONF_IMPORT_STATISTICS,
                default=defaults.get(CONF_IMPORT_STATISTICS, DEFAULT_IMPORT_STATISTICS),
            ): bool,
            vol.Required(
                CONF_GRID_PRICE_NET,
                default=defaults.get(CONF_GRID_PRICE_NET, DEFAULT_GRID_PRICE_NET),
            ): _number_box(
                min_value=MIN_PRICE_NET,
                max_value=MAX_PRICE_NET,
                step=0.00001,
                unit="EUR/kWh",
            ),
            vol.Required(
                CONF_SOLAR_PRICE_NET,
                default=defaults.get(CONF_SOLAR_PRICE_NET, DEFAULT_SOLAR_PRICE_NET),
            ): _number_box(
                min_value=MIN_PRICE_NET,
                max_value=MAX_PRICE_NET,
                step=0.00001,
                unit="EUR/kWh",
            ),
            vol.Required(
                CONF_TAX_RATE,
                default=defaults.get(CONF_TAX_RATE, DEFAULT_TAX_RATE),
            ): _number_box(min_value=MIN_TAX_RATE, max_value=MAX_TAX_RATE, step=0.01),
            vol.Required(
                CONF_MAX_INTERVAL_AVERAGE_KW,
                default=defaults.get(CONF_MAX_INTERVAL_AVERAGE_KW, DEFAULT_MAX_INTERVAL_AVERAGE_KW),
            ): _number_box(
                min_value=MIN_MAX_INTERVAL_AVERAGE_KW,
                max_value=MAX_MAX_INTERVAL_AVERAGE_KW,
                step=0.1,
                unit="kW",
            ),
            vol.Required(
                CONF_SMOOTH_INTERVAL_ANOMALIES,
                default=defaults.get(
                    CONF_SMOOTH_INTERVAL_ANOMALIES, DEFAULT_SMOOTH_INTERVAL_ANOMALIES
                ),
            ): bool,
            vol.Required(
                CONF_ANOMALY_REDISTRIBUTION_WINDOW,
                default=defaults.get(
                    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
                    DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
                ),
            ): _number_box(
                min_value=MIN_ANOMALY_REDISTRIBUTION_WINDOW,
                max_value=MAX_ANOMALY_REDISTRIBUTION_WINDOW,
                step=1,
                unit="buckets",
            ),
            vol.Required(
                CONF_SMOOTHING_LOOKAROUND_DAYS,
                default=defaults.get(
                    CONF_SMOOTHING_LOOKAROUND_DAYS, DEFAULT_SMOOTHING_LOOKAROUND_DAYS
                ),
            ): _number_box(
                min_value=MIN_SMOOTHING_LOOKAROUND_DAYS,
                max_value=MAX_SMOOTHING_LOOKAROUND_DAYS,
                step=1,
                unit="d",
            ),
            vol.Required(
                CONF_CACHE_INTERVAL_PAYLOADS,
                default=defaults.get(CONF_CACHE_INTERVAL_PAYLOADS, DEFAULT_CACHE_INTERVAL_PAYLOADS),
            ): bool,
            vol.Required(
                CONF_WEB_FALLBACK_ENABLED,
                default=defaults.get(CONF_WEB_FALLBACK_ENABLED, DEFAULT_WEB_FALLBACK_ENABLED),
            ): bool,
            vol.Optional(
                CONF_WEB_BASE_URL,
                default=defaults.get(CONF_WEB_BASE_URL, DEFAULT_WEB_BASE_URL),
            ): str,
            vol.Optional(
                CONF_WEB_SESSION_ID,
                default=defaults.get(CONF_WEB_SESSION_ID, ""),
            ): str,
            vol.Optional(
                CONF_WEB_COOKIE,
                default=defaults.get(CONF_WEB_COOKIE, ""),
            ): str,
            vol.Optional(
                CONF_WEB_GRAPH_TOTAL_ID,
                default=defaults.get(CONF_WEB_GRAPH_TOTAL_ID, DEFAULT_WEB_GRAPH_TOTAL_ID),
            ): str,
            vol.Required(
                CONF_BROWSER_PROXY_ENABLED,
                default=defaults.get(
                    CONF_BROWSER_PROXY_ENABLED, DEFAULT_BROWSER_PROXY_ENABLED
                ),
            ): bool,
            vol.Optional(
                CONF_BROWSER_PROXY_URL,
                default=defaults.get(CONF_BROWSER_PROXY_URL, DEFAULT_BROWSER_PROXY_URL),
            ): str,
            vol.Optional(
                CONF_BROWSER_PROXY_TOKEN,
                default=defaults.get(
                    CONF_BROWSER_PROXY_TOKEN, DEFAULT_BROWSER_PROXY_TOKEN
                ),
            ): str,
        }
    )


def _options_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return config entry options controlled by the UI."""
    return {
        CONF_POLL_INTERVAL: int(user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)),
        CONF_BACKFILL_DAYS: int(user_input.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS)),
        CONF_RECENT_REFRESH_HOURS: int(user_input.get(CONF_RECENT_REFRESH_HOURS, DEFAULT_RECENT_REFRESH_HOURS)),
        CONF_HISTORY_GRANULARITY: user_input.get(CONF_HISTORY_GRANULARITY, DEFAULT_HISTORY_GRANULARITY),
        CONF_IMPORT_STATISTICS: user_input.get(CONF_IMPORT_STATISTICS, DEFAULT_IMPORT_STATISTICS),
        CONF_GRID_PRICE_NET: float(user_input.get(CONF_GRID_PRICE_NET, DEFAULT_GRID_PRICE_NET)),
        CONF_SOLAR_PRICE_NET: float(user_input.get(CONF_SOLAR_PRICE_NET, DEFAULT_SOLAR_PRICE_NET)),
        CONF_TAX_RATE: float(user_input.get(CONF_TAX_RATE, DEFAULT_TAX_RATE)),
        CONF_MAX_INTERVAL_AVERAGE_KW: float(user_input.get(CONF_MAX_INTERVAL_AVERAGE_KW, DEFAULT_MAX_INTERVAL_AVERAGE_KW)),
        CONF_SMOOTH_INTERVAL_ANOMALIES: user_input.get(CONF_SMOOTH_INTERVAL_ANOMALIES, DEFAULT_SMOOTH_INTERVAL_ANOMALIES),
        CONF_ANOMALY_REDISTRIBUTION_WINDOW: int(user_input.get(CONF_ANOMALY_REDISTRIBUTION_WINDOW, DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW)),
        CONF_SMOOTHING_LOOKAROUND_DAYS: int(user_input.get(CONF_SMOOTHING_LOOKAROUND_DAYS, DEFAULT_SMOOTHING_LOOKAROUND_DAYS)),
        CONF_CACHE_INTERVAL_PAYLOADS: user_input.get(CONF_CACHE_INTERVAL_PAYLOADS, DEFAULT_CACHE_INTERVAL_PAYLOADS),
        CONF_WEB_FALLBACK_ENABLED: user_input.get(CONF_WEB_FALLBACK_ENABLED, DEFAULT_WEB_FALLBACK_ENABLED),
        CONF_WEB_BASE_URL: str(
            user_input.get(CONF_WEB_BASE_URL) or DEFAULT_WEB_BASE_URL
        ).rstrip("/"),
        CONF_WEB_SESSION_ID: str(user_input.get(CONF_WEB_SESSION_ID) or "").strip(),
        CONF_WEB_COOKIE: str(user_input.get(CONF_WEB_COOKIE) or "").strip(),
        CONF_WEB_GRAPH_TOTAL_ID: str(
            user_input.get(CONF_WEB_GRAPH_TOTAL_ID) or DEFAULT_WEB_GRAPH_TOTAL_ID
        ).strip(),
        CONF_BROWSER_PROXY_ENABLED: user_input.get(CONF_BROWSER_PROXY_ENABLED, DEFAULT_BROWSER_PROXY_ENABLED),
        CONF_BROWSER_PROXY_URL: str(
            user_input.get(CONF_BROWSER_PROXY_URL) or DEFAULT_BROWSER_PROXY_URL
        ).rstrip("/"),
        CONF_BROWSER_PROXY_TOKEN: str(
            user_input.get(CONF_BROWSER_PROXY_TOKEN) or DEFAULT_BROWSER_PROXY_TOKEN
        ).strip(),
    }


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
                    options=_options_from_input(user_input),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
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
                    options=_options_from_input(user_input),
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


class AstraEnergyOptionsFlow(config_entries.OptionsFlowWithReload):
    """Astra Energy options flow."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=_options_from_input(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self._config_entry.options)),
        )
