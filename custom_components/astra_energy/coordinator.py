"""Coordinator for Astra Energy."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AstraApiError,
    AstraAuthError,
    AstraClient,
    AstraDeferredDataError,
    AstraMeterReading,
    _cost_gross,
    _round_or_none,
    monotonic_reading,
)
from .const import (
    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
    CONF_BROWSER_PROXY_ENABLED,
    CONF_BROWSER_PROXY_TOKEN,
    CONF_BROWSER_PROXY_URL,
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
    DEFAULT_BROWSER_PROXY_ENABLED,
    DEFAULT_BROWSER_PROXY_TOKEN,
    DEFAULT_BROWSER_PROXY_URL,
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
    ISSUE_API_DEFERRED,
    ISSUE_API_UNAVAILABLE,
    ISSUE_WEB_SESSION,
    SENSOR_OBJECT_IDS,
)
from .browser_proxy import async_fetch_browser_proxy_readings
from .reporting import async_create_issue, async_delete_issue, error_payload
from .web_session import async_check_web_session

_LOGGER = logging.getLogger(__name__)

_BASELINE_ENERGY_STATISTIC_ATTRS = {
    "imported_energy": "grid_kwh_total",
    "solar_energy": "solar_kwh_total",
    "total_energy": "total_kwh",
}
_BASELINE_COST_STATISTIC_ATTRS = {
    "grid_energy_cost_total": "grid_kwh_total",
    "solar_energy_cost_total": "solar_kwh_total",
}
_MAX_STARTUP_BASELINE_REPAIR_KWH = 50.0
_MAX_STARTUP_BASELINE_HOLD_KWH = 1500.0


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
        self.browser_proxy_status: dict[str, str | int | None] = {
            "status": "disabled",
            "checked_at": None,
            "message": None,
            "url": None,
            "reading_count": None,
        }
        self._recorder_baselines_loaded = False
        self._last_mobile_success_at = None

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
        except AstraDeferredDataError as err:
            self.api_status = "deferred"
            self.last_error = error_payload(err)
            await self._async_update_web_session_status()
            browser_proxy_readings = await self._async_browser_proxy_fallback_readings()
            if browser_proxy_readings:
                await async_delete_issue(self.hass, ISSUE_API_AUTH)
                await async_delete_issue(self.hass, ISSUE_API_DEFERRED)
                await async_delete_issue(self.hass, ISSUE_API_UNAVAILABLE)
                return browser_proxy_readings
            if self.browser_proxy_status.get("status") == "rejected":
                return self.data or {}
            await async_delete_issue(self.hass, ISSUE_API_UNAVAILABLE)
            await async_create_issue(
                self.hass,
                ISSUE_API_DEFERRED,
                translation_key=ISSUE_API_DEFERRED,
                severity="warning",
                placeholders={"error": str(err)},
                notification_title="Astra Energy data deferred",
                notification_message=(
                    "Astra returned an empty, malformed, or incomplete payload. "
                    "Astra Energy is withholding cumulative energy sensors so "
                    "Home Assistant does not record invalid statistics. Last "
                    f"error: {type(err).__name__}: {err}"
                ),
            )
            _LOGGER.warning("Astra Energy update deferred: %s", err)
            if self.data:
                return self.data
            return await self._async_recorder_fallback_readings()
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

        now = dt_util.utcnow()
        previous_readings = await self._async_previous_readings(readings)
        live_elapsed_hours = _elapsed_hours(self._last_mobile_success_at, now)
        max_average_kw = float(
            self.config_entry.options.get(
                CONF_MAX_INTERVAL_AVERAGE_KW,
                DEFAULT_MAX_INTERVAL_AVERAGE_KW,
            )
        )
        normalized_readings = {}
        for reading in readings:
            previous = previous_readings.get(reading.meter_id) if previous_readings else None
            if _has_implausible_live_jump(
                reading,
                previous,
                max_average_kw=max_average_kw,
                elapsed_hours=_reading_elapsed_hours(reading, previous)
                or live_elapsed_hours,
            ):
                err = AstraDeferredDataError(
                    "Astra live meter payload contains an implausible cumulative jump"
                )
                self.api_status = "deferred"
                self.last_error = error_payload(err)
                await self._async_update_web_session_status()
                await async_delete_issue(self.hass, ISSUE_API_UNAVAILABLE)
                await async_create_issue(
                    self.hass,
                    ISSUE_API_DEFERRED,
                    translation_key=ISSUE_API_DEFERRED,
                    severity="warning",
                    placeholders={"error": str(err)},
                    notification_title="Astra Energy data deferred",
                    notification_message=(
                        "Astra returned an implausible live cumulative meter jump. "
                        "Astra Energy withheld cumulative energy sensors so "
                        "Home Assistant does not record invalid statistics. Last "
                        f"error: {type(err).__name__}: {err}"
                    ),
                )
                _LOGGER.warning(
                    "Astra Energy update deferred because of an implausible live jump"
                )
                return self.data or {}
            normalized_readings[reading.meter_id] = monotonic_reading(reading, previous)

        self.api_status = "ok"
        self.last_successful_source = "mobile"
        self.last_error = None
        self._last_mobile_success_at = now
        await self._async_update_web_session_status()
        self._set_browser_proxy_status("idle")
        await async_delete_issue(self.hass, ISSUE_API_AUTH)
        await async_delete_issue(self.hass, ISSUE_API_DEFERRED)
        await async_delete_issue(self.hass, ISSUE_API_UNAVAILABLE)
        return normalized_readings

    async def _async_previous_readings(
        self, readings: list[AstraMeterReading]
    ) -> dict[str, AstraMeterReading]:
        """Return in-memory and recorder-backed readings for monotonic repair."""
        previous_readings = dict(self.data or {})
        recorder_readings = await self._async_recorder_baseline_readings(
            readings,
            force=bool(previous_readings),
        )
        for meter_id, recorder_reading in recorder_readings.items():
            previous_readings[meter_id] = monotonic_reading(
                recorder_reading,
                previous_readings.get(meter_id),
            )
        return previous_readings

    async def _async_recorder_baseline_readings(
        self, readings: list[AstraMeterReading], *, force: bool = False
    ) -> dict[str, AstraMeterReading]:
        """Return startup baselines from recorder so monotonic repair survives restarts."""
        if self._recorder_baselines_loaded and not force:
            return {}
        if not force:
            self._recorder_baselines_loaded = True
        statistic_ids = {
            f"sensor.{SENSOR_OBJECT_IDS[channel]}"
            for channel in _BASELINE_ENERGY_STATISTIC_ATTRS
        } | {
            f"sensor.{SENSOR_OBJECT_IDS[channel]}"
            for channel in _BASELINE_COST_STATISTIC_ATTRS
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

    async def _async_recorder_fallback_readings(self) -> dict[str, AstraMeterReading]:
        """Return recorder-backed readings when Astra defers during startup."""
        if self._recorder_baselines_loaded:
            return {}
        self._recorder_baselines_loaded = True
        meter_id = _meter_id_from_entity_registry(self.hass)
        if meter_id is None:
            return {}
        statistic_ids = {
            f"sensor.{SENSOR_OBJECT_IDS[channel]}"
            for channel in _BASELINE_ENERGY_STATISTIC_ATTRS
        } | {
            f"sensor.{SENSOR_OBJECT_IDS[channel]}"
            for channel in _BASELINE_COST_STATISTIC_ATTRS
        }
        baselines = await _async_recorder_baseline_states(self.hass, statistic_ids)
        fallback = _recorder_fallback_reading_from_statistics(
            meter_id,
            baselines,
            self.config_entry.options,
        )
        if fallback is None:
            return {}
        self.last_successful_source = "recorder"
        return {fallback.meter_id: fallback}

    async def _async_browser_proxy_fallback_readings(
        self,
    ) -> dict[str, AstraMeterReading] | None:
        """Return browser-proxy readings when the mobile API returns deferred data."""
        if not self.config_entry.options.get(
            CONF_BROWSER_PROXY_ENABLED, DEFAULT_BROWSER_PROXY_ENABLED
        ):
            self._set_browser_proxy_status("disabled")
            return None
        url = str(
            self.config_entry.options.get(
                CONF_BROWSER_PROXY_URL, DEFAULT_BROWSER_PROXY_URL
            )
            or ""
        ).rstrip("/")
        if not url:
            self._set_browser_proxy_status(
                "not_configured", message="Astra browser proxy URL is empty"
            )
            return None

        try:
            readings = await async_fetch_browser_proxy_readings(
                async_get_clientsession(self.hass),
                url=url,
                token=self.config_entry.options.get(
                    CONF_BROWSER_PROXY_TOKEN, DEFAULT_BROWSER_PROXY_TOKEN
                ),
                grid_price_net=float(
                    self.config_entry.options.get(
                        CONF_GRID_PRICE_NET, DEFAULT_GRID_PRICE_NET
                    )
                ),
                solar_price_net=float(
                    self.config_entry.options.get(
                        CONF_SOLAR_PRICE_NET, DEFAULT_SOLAR_PRICE_NET
                    )
                ),
                tax_rate=float(
                    self.config_entry.options.get(CONF_TAX_RATE, DEFAULT_TAX_RATE)
                ),
            )
        except AstraApiError as err:
            self._set_browser_proxy_status("error", message=str(err), url=url)
            _LOGGER.warning("Astra browser proxy fallback failed: %s", err)
            return None

        now = dt_util.utcnow()
        previous_readings = await self._async_previous_readings(readings)
        live_elapsed_hours = _elapsed_hours(self._last_mobile_success_at, now)
        max_average_kw = float(
            self.config_entry.options.get(
                CONF_MAX_INTERVAL_AVERAGE_KW,
                DEFAULT_MAX_INTERVAL_AVERAGE_KW,
            )
        )
        normalized_readings = {}
        for reading in readings:
            previous = previous_readings.get(reading.meter_id) if previous_readings else None
            if _has_implausible_live_jump(
                reading,
                previous,
                max_average_kw=max_average_kw,
                elapsed_hours=_reading_elapsed_hours(reading, previous)
                or live_elapsed_hours,
            ):
                self._set_browser_proxy_status(
                    "rejected",
                    message="Browser proxy reading contains an implausible cumulative jump",
                    url=url,
                    reading_count=len(readings),
                )
                return None
            normalized_readings[reading.meter_id] = monotonic_reading(reading, previous)

        self.api_status = "browser_proxy"
        self.last_successful_source = "browser_proxy"
        self.last_error = None
        self._set_browser_proxy_status(
            "ok", url=url, reading_count=len(normalized_readings)
        )
        return normalized_readings

    def _set_browser_proxy_status(
        self,
        status: str,
        *,
        message: str | None = None,
        url: str | None = None,
        reading_count: int | None = None,
    ) -> None:
        """Update redaction-safe browser proxy diagnostics."""
        self.browser_proxy_status = {
            "status": status,
            "checked_at": datetime.now().isoformat(),
            "message": message,
            "url": url,
            "reading_count": reading_count,
        }

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
    """Return the maximum plausible available state for each statistic id."""
    states: dict[str, float] = {}
    for statistic_id, rows in rows_by_statistic_id.items():
        present_states = _plausible_statistic_states(statistic_id, rows)
        if present_states:
            states[statistic_id] = max(present_states)
    return states


def _plausible_statistic_states(statistic_id: str, rows: list[dict]) -> list[float]:
    """Return statistic states after skipping implausible one-step jumps."""
    plausible: list[float] = []
    previous_state: float | None = None
    previous_start: float | None = None
    for row in sorted(rows, key=lambda item: item.get("start") or 0):
        state = row.get("state")
        if state is None:
            continue
        current_state = float(state)
        current_start = _statistic_start_seconds(row.get("start"))
        if (
            previous_state is not None
            and current_state > previous_state
            and _statistic_delta_exceeds_limit(
                current_state - previous_state,
                previous_start,
                current_start,
            )
        ):
            _LOGGER.warning(
                "Ignoring implausible Astra recorder baseline statistic=%s "
                "previous=%s current=%s start=%s",
                statistic_id,
                previous_state,
                current_state,
                current_start,
            )
            continue
        plausible.append(current_state)
        previous_state = current_state
        previous_start = current_start
    return plausible


def _statistic_delta_exceeds_limit(
    delta: float,
    previous_start: float | None,
    current_start: float | None,
) -> bool:
    """Return whether a recorder delta is too large to trust as a baseline."""
    if previous_start is not None and current_start is not None:
        elapsed_hours = max((current_start - previous_start) / 3600, 1.0)
        return delta > _MAX_STARTUP_BASELINE_REPAIR_KWH * elapsed_hours
    return delta > _MAX_STARTUP_BASELINE_REPAIR_KWH


def _statistic_start_seconds(value) -> float | None:
    """Return a statistic row start as UNIX seconds when available."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    numeric = float(value)
    if numeric > 10_000_000_000:
        return numeric / 1000
    return numeric


def _elapsed_hours(start: datetime | None, end: datetime) -> float | None:
    """Return positive elapsed hours between two update timestamps."""
    if start is None:
        return None
    elapsed = (end - start).total_seconds() / 3600
    if elapsed <= 0:
        return None
    return elapsed


def _reading_elapsed_hours(
    reading: AstraMeterReading,
    previous: AstraMeterReading | None,
) -> float | None:
    """Return elapsed hours between provider timestamps when both are known."""
    if previous is None or reading.timestamp is None or previous.timestamp is None:
        return None
    return _elapsed_hours(previous.timestamp, reading.timestamp)


def _has_implausible_live_jump(
    reading: AstraMeterReading,
    previous: AstraMeterReading | None,
    *,
    max_average_kw: float,
    elapsed_hours: float | None,
) -> bool:
    """Return whether a live cumulative update is too large to publish."""
    if previous is None:
        return False
    max_delta = (
        max_average_kw * max(elapsed_hours, 0.25)
        if elapsed_hours is not None
        else _MAX_STARTUP_BASELINE_REPAIR_KWH
    )
    checks = (
        ("grid", reading.grid_kwh_total, previous.grid_kwh_total),
        ("imported", reading.imported_kwh_total, previous.imported_kwh_total),
        ("solar", reading.solar_kwh_total, previous.solar_kwh_total),
        ("total", reading.total_kwh, previous.total_kwh),
    )
    for label, current, prior in checks:
        if current is None or prior is None:
            continue
        delta = current - prior
        if delta > max_delta:
            _LOGGER.warning(
                "Rejecting Astra live %s jump: previous=%s current=%s delta=%s limit=%s",
                label,
                prior,
                current,
                delta,
                max_delta,
            )
            return True
    return False


def _meter_id_from_entity_registry(hass: HomeAssistant) -> str | None:
    """Return the existing Astra meter ID from the entity registry."""
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return None
    registry = er.async_get(hass)
    entity = registry.async_get(f"sensor.{SENSOR_OBJECT_IDS['imported_energy']}")
    unique_id = getattr(entity, "unique_id", None) if entity is not None else None
    prefix = f"{DOMAIN}_"
    suffix = "_imported_energy"
    if not unique_id or not unique_id.startswith(prefix) or not unique_id.endswith(suffix):
        return None
    meter_id = unique_id[len(prefix) : -len(suffix)]
    return meter_id or None


def _recorder_fallback_reading_from_statistics(
    meter_id: str,
    statistic_states: dict[str, float],
    options: dict,
) -> AstraMeterReading | None:
    """Build one stable reading from recorder statistics during provider deferrals."""
    grid = statistic_states.get(f"sensor.{SENSOR_OBJECT_IDS['imported_energy']}")
    solar = statistic_states.get(f"sensor.{SENSOR_OBJECT_IDS['solar_energy']}")
    total = statistic_states.get(f"sensor.{SENSOR_OBJECT_IDS['total_energy']}")
    if total is None and (grid is not None or solar is not None):
        total = (grid or 0.0) + (solar or 0.0)
    if grid is None and total is not None and solar is not None:
        grid = max(total - solar, 0.0)
    if grid is not None and total is not None:
        plausible_solar = max(total - grid, 0.0)
        if solar is None or solar - plausible_solar > _MAX_STARTUP_BASELINE_REPAIR_KWH:
            solar = plausible_solar
    if solar is not None and total is not None:
        plausible_grid = max(total - solar, 0.0)
        if grid is None or grid - plausible_grid > _MAX_STARTUP_BASELINE_REPAIR_KWH:
            grid = plausible_grid
    if all(value is None for value in (grid, solar, total)):
        return None

    grid_price_net = float(options.get(CONF_GRID_PRICE_NET, DEFAULT_GRID_PRICE_NET))
    solar_price_net = float(options.get(CONF_SOLAR_PRICE_NET, DEFAULT_SOLAR_PRICE_NET))
    tax_rate = float(options.get(CONF_TAX_RATE, DEFAULT_TAX_RATE))
    grid_price_gross = _round_or_none(grid_price_net * (1 + tax_rate))
    solar_price_gross = _round_or_none(solar_price_net * (1 + tax_rate))
    grid_cost = statistic_states.get(f"sensor.{SENSOR_OBJECT_IDS['grid_energy_cost_total']}")
    solar_cost = statistic_states.get(f"sensor.{SENSOR_OBJECT_IDS['solar_energy_cost_total']}")
    if grid_cost is None:
        grid_cost = _cost_gross(grid, grid_price_gross)
    if solar_cost is None:
        solar_cost = _cost_gross(solar, solar_price_gross)
    total_cost = (
        _round_or_none((grid_cost or 0.0) + (solar_cost or 0.0), 4)
        if grid_cost is not None or solar_cost is not None
        else None
    )
    return AstraMeterReading(
        meter_id=meter_id,
        meter_name="Astra Energy Meter",
        timestamp=None,
        power_w=None,
        imported_kwh_total=grid,
        grid_kwh_total=grid,
        solar_kwh_total=solar,
        total_kwh=total,
        unsmoothed_grid_kwh_total=grid,
        unsmoothed_solar_kwh_total=solar,
        unsmoothed_total_kwh=total,
        grid_price_net_eur_per_kwh=grid_price_net,
        grid_price_gross_eur_per_kwh=grid_price_gross,
        solar_price_net_eur_per_kwh=solar_price_net,
        solar_price_gross_eur_per_kwh=solar_price_gross,
        tax_rate=tax_rate,
        grid_cost_total_gross_eur=grid_cost,
        solar_cost_total_gross_eur=solar_cost,
        total_cost_total_gross_eur=total_cost,
        raw={"source": "recorder_fallback"},
    )


def _baseline_reading_from_statistics(
    reading: AstraMeterReading, statistic_states: dict[str, float]
) -> AstraMeterReading | None:
    """Build a previous reading from recorder statistic states."""
    grid_provider = reading.grid_kwh_total or reading.imported_kwh_total
    energy_values = {
        attr: statistic_states.get(f"sensor.{SENSOR_OBJECT_IDS[channel]}")
        for channel, attr in _BASELINE_ENERGY_STATISTIC_ATTRS.items()
    }
    cost_derived_values = _cost_derived_baselines(reading, statistic_states)
    values = {
        attr: _best_plausible_baseline_value(
            (energy_values.get(attr), cost_derived_values.get(attr)),
            (
                grid_provider
                if attr == "grid_kwh_total"
                else reading.solar_kwh_total
                if attr == "solar_kwh_total"
                else reading.total_kwh
            ),
        )
        for attr in _BASELINE_ENERGY_STATISTIC_ATTRS.values()
    }
    values = _hold_consistent_recorder_baseline_on_large_provider_rollback(
        values,
        energy_values,
        reading,
    )
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


def _hold_consistent_recorder_baseline_on_large_provider_rollback(
    values: dict[str, float | None],
    energy_values: dict[str, float | None],
    reading: AstraMeterReading,
) -> dict[str, float | None]:
    """Hold recorder maxima when Astra publishes a large lower counter set."""
    grid = energy_values.get("grid_kwh_total")
    solar = energy_values.get("solar_kwh_total")
    total = energy_values.get("total_kwh")
    provider_grid = reading.grid_kwh_total or reading.imported_kwh_total
    provider_solar = reading.solar_kwh_total
    provider_total = reading.total_kwh
    if grid is None or solar is None or total is None:
        return values
    if abs((grid + solar) - total) > _MAX_STARTUP_BASELINE_REPAIR_KWH:
        return values

    provider_values = {
        "grid_kwh_total": provider_grid,
        "solar_kwh_total": provider_solar,
        "total_kwh": provider_total,
    }
    source_rollbacks = [
        baseline - provider
        for baseline, provider in ((grid, provider_grid), (solar, provider_solar))
        if provider is not None and baseline > provider
    ]
    if (
        len(source_rollbacks) < 2
        or any(rollback <= _MAX_STARTUP_BASELINE_REPAIR_KWH for rollback in source_rollbacks)
        or any(rollback > _MAX_STARTUP_BASELINE_HOLD_KWH for rollback in source_rollbacks)
    ):
        return values
    held = dict(values)
    for attr, baseline in (
        ("grid_kwh_total", grid),
        ("solar_kwh_total", solar),
        ("total_kwh", total),
    ):
        provider = provider_values[attr]
        if provider is None or baseline <= provider:
            continue
        rollback = baseline - provider
        if (
            rollback > _MAX_STARTUP_BASELINE_REPAIR_KWH
            and rollback <= _MAX_STARTUP_BASELINE_HOLD_KWH
        ):
            held[attr] = baseline
    return held


def _cost_derived_baselines(
    reading: AstraMeterReading, statistic_states: dict[str, float]
) -> dict[str, float]:
    """Derive energy baselines from lifetime cost statistics and current prices."""
    values = {}
    price_by_attr = {
        "grid_kwh_total": reading.grid_price_gross_eur_per_kwh,
        "solar_kwh_total": reading.solar_price_gross_eur_per_kwh,
    }
    for channel, attr in _BASELINE_COST_STATISTIC_ATTRS.items():
        price = price_by_attr.get(attr)
        cost = statistic_states.get(f"sensor.{SENSOR_OBJECT_IDS[channel]}")
        if price is not None and price > 0 and cost is not None:
            values[attr] = cost / price
    return values


def _best_plausible_baseline_value(
    candidates: tuple[float | None, ...],
    provider: float | None,
) -> float | None:
    """Return the highest candidate that is plausible relative to the provider."""
    plausible = [
        value
        for value in (_plausible_baseline_value(candidate, provider) for candidate in candidates)
        if value is not None
    ]
    return max(plausible) if plausible else None


def _plausible_baseline_value(
    baseline: float | None,
    provider: float | None,
) -> float | None:
    """Return a startup baseline only when it is plausibly close to the provider."""
    if baseline is None:
        return None
    if provider is None:
        return baseline
    if baseline - provider > _MAX_STARTUP_BASELINE_REPAIR_KWH:
        return None
    return baseline
