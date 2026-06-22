"""Coordinator for Astra Energy."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AstraApiError,
    AstraAuthError,
    AstraClient,
    AstraMeterReading,
    monotonic_reading,
)
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
    SENSOR_OBJECT_IDS,
)
from .reporting import async_create_issue, async_delete_issue, error_payload
from .web_session import async_check_web_session

_LOGGER = logging.getLogger(__name__)

_BASELINE_STATISTIC_ATTRS = {
    "imported_energy": "grid_kwh_total",
    "solar_energy": "solar_kwh_total",
    "total_energy": "total_kwh",
}


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
        self._recorder_baselines_loaded = False

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
        previous_readings = self.data or await self._async_recorder_baseline_readings(readings)
        return {
            reading.meter_id: monotonic_reading(
                reading,
                previous_readings.get(reading.meter_id) if previous_readings else None,
            )
            for reading in readings
        }

    async def _async_recorder_baseline_readings(
        self, readings: list[AstraMeterReading]
    ) -> dict[str, AstraMeterReading]:
        """Return startup baselines from recorder so monotonic repair survives restarts."""
        if self._recorder_baselines_loaded:
            return {}
        self._recorder_baselines_loaded = True
        statistic_ids = {
            f"sensor.{SENSOR_OBJECT_IDS[channel]}"
            for channel in _BASELINE_STATISTIC_ATTRS
        }
        baselines = await _async_recorder_baseline_states(self.hass, statistic_ids)
        if not baselines:
            return {}
        baseline_readings = {}
        for reading in readings:
            baseline = _baseline_reading_from_statistics(reading, baselines)
            if baseline is not None:
                baseline_readings[reading.meter_id] = baseline
        return baseline_readings

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
            "missing_graph_id",
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


async def _async_recorder_baseline_states(
    hass: HomeAssistant, statistic_ids: set[str]
) -> dict[str, float]:  # pragma: no cover
    """Read monotonic recorder baselines for cumulative Astra energy sensors."""
    end = dt_util.utcnow()
    start = end - timedelta(days=30)

    def read_latest() -> dict[str, float]:
        try:
            from homeassistant.components.recorder.statistics import statistics_during_period
        except ImportError:
            return {}
        result = statistics_during_period(
            hass,
            start,
            end,
            statistic_ids,
            "hour",
            None,
            {"state"},
        )
        return _max_statistic_states(result)

    try:
        from homeassistant.components.recorder import get_instance
    except ImportError:
        return await hass.async_add_executor_job(read_latest)

    return await get_instance(hass).async_add_executor_job(read_latest)


def _max_statistic_states(rows_by_statistic_id: dict[str, list[dict]]) -> dict[str, float]:
    """Return the maximum available state for each statistic id."""
    states: dict[str, float] = {}
    for statistic_id, rows in rows_by_statistic_id.items():
        present_states = [float(row["state"]) for row in rows if row.get("state") is not None]
        if present_states:
            states[statistic_id] = max(present_states)
    return states


def _baseline_reading_from_statistics(
    reading: AstraMeterReading, statistic_states: dict[str, float]
) -> AstraMeterReading | None:
    """Build a previous reading from recorder statistic states."""
    values = {
        attr: statistic_states.get(f"sensor.{SENSOR_OBJECT_IDS[channel]}")
        for channel, attr in _BASELINE_STATISTIC_ATTRS.items()
    }
    if all(value is None for value in values.values()):
        return None
    return AstraMeterReading(
        meter_id=reading.meter_id,
        meter_name=reading.meter_name,
        timestamp=None,
        power_w=None,
        imported_kwh_total=values["grid_kwh_total"],
        grid_kwh_total=values["grid_kwh_total"],
        solar_kwh_total=values["solar_kwh_total"],
        total_kwh=values["total_kwh"],
        raw={"source": "recorder_baseline"},
    )
