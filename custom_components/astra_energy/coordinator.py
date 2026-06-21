"""Coordinator for Astra Energy."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AstraApiError, AstraAuthError, AstraClient, AstraMeterReading
from .const import (
    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
    CONF_GRID_PRICE_NET,
    CONF_MAX_INTERVAL_AVERAGE_KW,
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
    DEFAULT_GRID_PRICE_NET,
    DEFAULT_MAX_INTERVAL_AVERAGE_KW,
    DEFAULT_SMOOTH_INTERVAL_ANOMALIES,
    DEFAULT_SMOOTHING_LOOKAROUND_DAYS,
    DEFAULT_SOLAR_PRICE_NET,
    DEFAULT_TAX_RATE,
    DEFAULT_WEB_BASE_URL,
    DEFAULT_WEB_FALLBACK_ENABLED,
    DEFAULT_WEB_GRAPH_TOTAL_ID,
    DOMAIN,
    ISSUE_API_AUTH,
    ISSUE_API_UNAVAILABLE,
    ISSUE_WEB_SESSION,
)
from .reporting import async_create_issue, async_delete_issue, error_payload
from .web_session import async_check_web_session

_LOGGER = logging.getLogger(__name__)


class AstraEnergyCoordinator(DataUpdateCoordinator[dict[str, AstraMeterReading]]):
    """Fetch and normalize Astra meter readings."""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry,
        username: str,
        password: str,
        base_url: str,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=update_interval,
        )
        self.config_entry = entry
        self.client = AstraClient(
            async_get_clientsession(hass),
            username=username,
            password=password,
            base_url=base_url,
            grid_price_net=entry.options.get(CONF_GRID_PRICE_NET, DEFAULT_GRID_PRICE_NET),
            solar_price_net=entry.options.get(CONF_SOLAR_PRICE_NET, DEFAULT_SOLAR_PRICE_NET),
            tax_rate=entry.options.get(CONF_TAX_RATE, DEFAULT_TAX_RATE),
            max_interval_average_kw=entry.options.get(
                CONF_MAX_INTERVAL_AVERAGE_KW, DEFAULT_MAX_INTERVAL_AVERAGE_KW
            ),
            smooth_interval_anomalies=entry.options.get(
                CONF_SMOOTH_INTERVAL_ANOMALIES, DEFAULT_SMOOTH_INTERVAL_ANOMALIES
            ),
            anomaly_redistribution_window=entry.options.get(
                CONF_ANOMALY_REDISTRIBUTION_WINDOW,
                DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
            ),
            smoothing_lookaround_days=entry.options.get(
                CONF_SMOOTHING_LOOKAROUND_DAYS, DEFAULT_SMOOTHING_LOOKAROUND_DAYS
            ),
        )
        self.last_error: dict[str, str] | None = None
        self.api_status = "unknown"
        self.last_successful_source: str | None = None
        self.web_session_status: dict[str, str | int | None] = {
            "status": "disabled",
            "checked_at": None,
            "message": None,
            "graph_id": None,
            "point_count": None,
            "response_bytes": None,
        }

    async def _async_update_data(self) -> dict[str, AstraMeterReading]:
        """Fetch latest Astra data."""
        try:
            readings = await self.client.async_get_meters()
        except AstraAuthError as err:
            self.api_status = "invalid_auth"
            self.last_error = error_payload(err)
            await async_create_issue(
                self.hass,
                ISSUE_API_AUTH,
                translation_key=ISSUE_API_AUTH,
                placeholders={"error": str(err)},
                notification_title="Astra Energy authentication failed",
                notification_message=(
                    "Astra rejected the stored credentials. Reauthenticate the "
                    "Astra Energy integration from Settings > Devices & services."
                ),
            )
            raise ConfigEntryAuthFailed(str(err)) from err
        except AstraApiError as err:
            self.api_status = "error"
            self.last_error = error_payload(err)
            await self._async_update_web_session_status()
            await async_create_issue(
                self.hass,
                ISSUE_API_UNAVAILABLE,
                translation_key=ISSUE_API_UNAVAILABLE,
                placeholders={"error": str(err)},
                notification_title="Astra Energy update failed",
                notification_message=(
                    "Astra Energy could not fetch meter data. Home Assistant will "
                    "retry automatically. Last error: "
                    f"{type(err).__name__}: {err}"
                ),
            )
            raise UpdateFailed(str(err)) from err

        self.api_status = "ok"
        self.last_successful_source = "mobile"
        self.last_error = None
        await self._async_update_web_session_status()
        await async_delete_issue(self.hass, ISSUE_API_AUTH)
        await async_delete_issue(self.hass, ISSUE_API_UNAVAILABLE)
        return {reading.meter_id: reading for reading in readings}

    async def _async_update_web_session_status(self) -> None:
        """Check the optional manual browser session and publish diagnostics."""
        if not self.config_entry.options.get(
            CONF_WEB_FALLBACK_ENABLED, DEFAULT_WEB_FALLBACK_ENABLED
        ):
            self.web_session_status = {
                "status": "disabled",
                "checked_at": None,
                "message": None,
                "graph_id": None,
                "point_count": None,
                "response_bytes": None,
            }
            await async_delete_issue(self.hass, ISSUE_WEB_SESSION)
            return

        status = await async_check_web_session(
            async_get_clientsession(self.hass),
            base_url=self.config_entry.options.get(CONF_WEB_BASE_URL, DEFAULT_WEB_BASE_URL),
            session_id=self.config_entry.options.get(CONF_WEB_SESSION_ID),
            cookie=self.config_entry.options.get(CONF_WEB_COOKIE),
            graph_id=self.config_entry.options.get(
                CONF_WEB_GRAPH_TOTAL_ID, DEFAULT_WEB_GRAPH_TOTAL_ID
            ),
        )
        self.web_session_status = status.as_dict()
        if status.status == "ok":
            await async_delete_issue(self.hass, ISSUE_WEB_SESSION)
            return
        if status.status in {
            "expired",
            "invalid_response",
            "login_required",
            "missing_cookie",
            "missing_session_id",
            "no_data",
            "unreachable",
        }:
            await async_create_issue(
                self.hass,
                ISSUE_WEB_SESSION,
                translation_key=ISSUE_WEB_SESSION,
                placeholders={"error": status.message or status.status},
                notification_title="Astra Energy web session failed",
                notification_message=(
                    "The optional Astra browser-session fallback is configured but "
                    f"not usable: {status.status}. {status.message or ''}".strip()
                ),
            )
