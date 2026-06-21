"""Long-term statistics import helpers for Astra Energy."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api import AstraMeterReading
from .const import (
    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
    HISTORY_GRANULARITY_MONTHLY,
    HISTORY_GRANULARITY_QUARTER_HOUR,
    CONF_CACHE_INTERVAL_PAYLOADS,
    CONF_MAX_INTERVAL_AVERAGE_KW,
    CONF_SMOOTH_INTERVAL_ANOMALIES,
    CONF_SMOOTHING_LOOKAROUND_DAYS,
    DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
    DEFAULT_CACHE_INTERVAL_PAYLOADS,
    DEFAULT_MAX_INTERVAL_AVERAGE_KW,
    DEFAULT_SMOOTH_INTERVAL_ANOMALIES,
    DEFAULT_SMOOTHING_LOOKAROUND_DAYS,
    ISSUE_BACKFILL_FAILED,
    SENSOR_DISPLAY_NAMES,
    SENSOR_OBJECT_IDS,
)
from .coordinator import AstraEnergyCoordinator
from .reporting import async_create_issue, async_delete_issue, summarize_counts

_LOGGER = logging.getLogger(__name__)

RECORDER_SOURCE = "recorder"
INTERVAL_CACHE_STORAGE_KEY = "astra_energy.interval_payload_cache"
INTERVAL_CACHE_STORAGE_VERSION = 1

STATISTIC_CHANNELS = {
    "imported_energy": ("grid_kwh_total", EnergyConverter.UNIT_CLASS, UnitOfEnergy.KILO_WATT_HOUR),
    "solar_energy": ("solar_kwh_total", EnergyConverter.UNIT_CLASS, UnitOfEnergy.KILO_WATT_HOUR),
    "total_energy": ("total_kwh", EnergyConverter.UNIT_CLASS, UnitOfEnergy.KILO_WATT_HOUR),
    "unsmoothed_imported_energy": (
        "unsmoothed_grid_kwh_total",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    "unsmoothed_solar_energy": (
        "unsmoothed_solar_kwh_total",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    "unsmoothed_total_energy": (
        "unsmoothed_total_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    "grid_energy_cost_total": ("grid_cost_total_gross_eur", None, "EUR"),
    "solar_energy_cost_total": ("solar_cost_total_gross_eur", None, "EUR"),
    "total_energy_cost_total": ("total_cost_total_gross_eur", None, "EUR"),
}


def _sensor_statistic_id(reading: AstraMeterReading, channel: str) -> str:
    """Return the entity statistic id used by the energy sensor."""
    return f"sensor.{SENSOR_OBJECT_IDS[channel]}"


def _statistics_hour_start(timestamp: datetime) -> datetime:
    """Return the long-term statistics hour for an interval-end timestamp."""
    start = timestamp.replace(minute=0, second=0, microsecond=0)
    if timestamp == start:
        return start - timedelta(hours=1)
    return start


def _statistics_rows(
    readings: list[AstraMeterReading],
    value_attr: str,
    *,
    align_to_hour: bool = False,
    sum_start: float = 0.0,
) -> list[dict]:
    """Convert cumulative meter readings to recorder statistics rows."""
    rows_by_start = {}
    previous_total: float | None = None
    current_sum = sum_start
    for reading in sorted(
        readings,
        key=lambda item: (item.timestamp or dt_util.utcnow(), item.meter_id),
    ):
        total = getattr(reading, value_attr)
        if reading.timestamp is None or total is None:
            continue
        if previous_total is not None:
            current_sum += max(total - previous_total, 0.0)
        previous_total = total
        timestamp = dt_util.as_utc(reading.timestamp)
        start = _statistics_hour_start(timestamp) if align_to_hour else timestamp
        rows_by_start[start] = {
            "start": start,
            "state": total,
            "sum": current_sum,
        }
    return list(rows_by_start.values())


async def _async_sum_starts(
    hass: HomeAssistant,
    statistic_ids: set[str],
    start: datetime,
) -> dict[str, float]:  # pragma: no cover
    """Return recorder sums immediately before the imported window."""
    query_start = start - timedelta(days=7)

    def read_sums() -> dict[str, float]:
        try:
            from homeassistant.components.recorder.statistics import statistics_during_period
        except ImportError:
            return {}
        result = statistics_during_period(
            hass,
            query_start,
            start,
            statistic_ids,
            "hour",
            None,
            {"sum"},
        )
        sums = {}
        for statistic_id, rows in result.items():
            for row in reversed(rows):
                total = row.get("sum")
                if total is not None:
                    sums[statistic_id] = total
                    break
        return sums

    try:
        from homeassistant.components.recorder import get_instance
    except ImportError:
        return await hass.async_add_executor_job(read_sums)

    return await get_instance(hass).async_add_executor_job(read_sums)


async def _async_interval_payload_cache(  # pragma: no cover
    hass: HomeAssistant,
) -> dict[str, dict[str, Any]]:
    """Load persisted quarter-hour payload cache."""
    try:
        from homeassistant.helpers.storage import Store
    except ImportError:
        return {}
    store = Store(hass, INTERVAL_CACHE_STORAGE_VERSION, INTERVAL_CACHE_STORAGE_KEY)
    data = await store.async_load() or {}
    if not isinstance(data, dict):
        return {}
    return data


async def _async_save_interval_payload_cache(  # pragma: no cover
    hass: HomeAssistant,
    cache: dict[str, dict[str, Any]],
) -> None:
    """Persist quarter-hour payload cache."""
    try:
        from homeassistant.helpers.storage import Store
    except ImportError:
        return
    store = Store(hass, INTERVAL_CACHE_STORAGE_VERSION, INTERVAL_CACHE_STORAGE_KEY)
    await store.async_save(cache)


async def async_backfill_statistics(  # pragma: no cover
    hass: HomeAssistant,
    coordinator: AstraEnergyCoordinator,
    *,
    days: int,
    recent_refresh_hours: int,
    history_granularity: str,
    import_statistics: bool,
    max_average_kw: float | None = None,
    smooth_anomalies: bool | None = None,
    redistribution_window: int | None = None,
    smoothing_lookaround_days: int | None = None,
    cache_interval_payloads: bool | None = None,
) -> dict[str, int]:
    """Fetch historical readings and optionally import long-term statistics."""
    if days <= 0 and recent_refresh_hours <= 0:
        return {}
    end = dt_util.utcnow()
    start_candidates = []
    if days > 0:
        start_candidates.append(end - timedelta(days=days))
    if recent_refresh_hours > 0:
        start_candidates.append(end - timedelta(hours=recent_refresh_hours))
    start = min(start_candidates)
    if history_granularity == HISTORY_GRANULARITY_QUARTER_HOUR:
        use_cache = (
            coordinator.config_entry.options.get(
                CONF_CACHE_INTERVAL_PAYLOADS, DEFAULT_CACHE_INTERVAL_PAYLOADS
            )
            if cache_interval_payloads is None
            else cache_interval_payloads
        )
        payload_cache = await _async_interval_payload_cache(hass) if use_cache else {}
        cache_size_before = len(payload_cache)
        cache_before = end - timedelta(hours=recent_refresh_hours) if use_cache else None
        readings = await coordinator.client.async_get_historical_interval_meter_stands(
            start,
            end,
            payload_cache=payload_cache if use_cache else None,
            cache_before=cache_before,
            max_average_kw=(
                coordinator.config_entry.options.get(
                    CONF_MAX_INTERVAL_AVERAGE_KW, DEFAULT_MAX_INTERVAL_AVERAGE_KW
                )
                if max_average_kw is None
                else max_average_kw
            ),
            smooth_anomalies=(
                coordinator.config_entry.options.get(
                    CONF_SMOOTH_INTERVAL_ANOMALIES, DEFAULT_SMOOTH_INTERVAL_ANOMALIES
                )
                if smooth_anomalies is None
                else smooth_anomalies
            ),
            redistribution_window=(
                coordinator.config_entry.options.get(
                    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
                    DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
                )
                if redistribution_window is None
                else redistribution_window
            ),
            smoothing_lookaround_days=(
                coordinator.config_entry.options.get(
                    CONF_SMOOTHING_LOOKAROUND_DAYS, DEFAULT_SMOOTHING_LOOKAROUND_DAYS
                )
                if smoothing_lookaround_days is None
                else smoothing_lookaround_days
            ),
        )
        if use_cache and len(payload_cache) != cache_size_before:
            await _async_save_interval_payload_cache(hass, payload_cache)
    else:
        history_granularity = HISTORY_GRANULARITY_MONTHLY
        readings = await coordinator.client.async_get_historical_meter_stands(start, end)
    grouped: dict[str, list[AstraMeterReading]] = {}
    for reading in readings:
        grouped.setdefault(reading.meter_id, []).append(reading)

    if not import_statistics:
        _LOGGER.info(
            "Fetched Astra %s historical readings; statistics import disabled: %s",
            history_granularity,
            summarize_counts({meter_id: len(rows) for meter_id, rows in grouped.items()}),
        )
        await async_delete_issue(hass, ISSUE_BACKFILL_FAILED)
        return {meter_id: len(meter_readings) for meter_id, meter_readings in grouped.items()}

    try:
        from homeassistant.components.recorder.models import (
            StatisticData,
            StatisticMeanType,
            StatisticMetaData,
        )
        from homeassistant.components.recorder.statistics import async_import_statistics
    except ImportError as err:
        await async_create_issue(
            hass,
            ISSUE_BACKFILL_FAILED,
            translation_key=ISSUE_BACKFILL_FAILED,
            placeholders={"error": "Recorder statistics API is not available"},
            notification_title="Astra Energy backfill failed",
            notification_message="Recorder statistics API is not available.",
        )
        raise HomeAssistantError("Recorder statistics API is not available") from err

    statistic_ids = {
        _sensor_statistic_id(meter_readings[-1], channel)
        for meter_readings in grouped.values()
        if meter_readings
        for channel in STATISTIC_CHANNELS
    }
    sum_starts = await _async_sum_starts(hass, statistic_ids, start)

    for meter_id, meter_readings in grouped.items():
        if not meter_readings:
            continue
        for channel, (value_attr, unit_class, unit_of_measurement) in STATISTIC_CHANNELS.items():
            statistic_id = _sensor_statistic_id(meter_readings[-1], channel)
            metadata = StatisticMetaData(
                has_sum=True,
                mean_type=StatisticMeanType.NONE,
                name=SENSOR_DISPLAY_NAMES[channel],
                source=RECORDER_SOURCE,
                statistic_id=statistic_id,
                unit_class=unit_class,
                unit_of_measurement=unit_of_measurement,
            )
            rows = [
                StatisticData(start=row["start"], state=row["state"], sum=row["sum"])
                for row in _statistics_rows(
                    meter_readings,
                    value_attr,
                    align_to_hour=history_granularity == HISTORY_GRANULARITY_QUARTER_HOUR,
                    sum_start=sum_starts.get(statistic_id, 0.0),
                )
            ]
            if rows:
                try:
                    async_import_statistics(hass, metadata, rows)
                except Exception as err:  # noqa: BLE001
                    await async_create_issue(
                        hass,
                        ISSUE_BACKFILL_FAILED,
                        translation_key=ISSUE_BACKFILL_FAILED,
                        placeholders={"error": str(err)},
                        notification_title="Astra Energy backfill failed",
                        notification_message=(
                            f"Could not import statistics for {statistic_id}: {err}"
                        ),
                    )
                    raise HomeAssistantError(
                        f"Could not import Astra statistics for {statistic_id}: {err}"
                    ) from err
                _LOGGER.info(
                    "Imported %s Astra statistic rows for %s",
                    len(rows),
                    statistic_id,
                )
    await async_delete_issue(hass, ISSUE_BACKFILL_FAILED)
    return {meter_id: len(meter_readings) for meter_id, meter_readings in grouped.items()}
