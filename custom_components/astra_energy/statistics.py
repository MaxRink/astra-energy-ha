"""Long-term statistics import helpers for Astra Energy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
STATISTIC_IMPORT_BATCH_SIZE = 250

@dataclass(frozen=True)
class StatisticChannel:
    """Recorder import description for one Astra sensor."""

    value_attr: str
    unit_class: str | None
    unit_of_measurement: str
    has_sum: bool = True
    has_mean: bool = False
    allow_reset: bool = False
    max_hourly_delta: bool = False
    value_multiplier: float = 1.0


STATISTIC_CHANNELS = {
    "grid_energy_cost_total": StatisticChannel("grid_cost_total_gross_eur", None, "EUR"),
    "solar_energy_cost_total": StatisticChannel("solar_cost_total_gross_eur", None, "EUR"),
    "total_energy_cost_total": StatisticChannel("total_cost_total_gross_eur", None, "EUR"),
    "current_month_grid_cost": StatisticChannel(
        "current_month_grid_cost_gross_eur",
        None,
        "EUR",
        has_sum=False,
    ),
    "current_month_solar_cost": StatisticChannel(
        "current_month_solar_cost_gross_eur",
        None,
        "EUR",
        has_sum=False,
    ),
    "current_month_total_cost": StatisticChannel(
        "current_month_total_cost_gross_eur",
        None,
        "EUR",
        has_sum=False,
    ),
    "current_year_grid_cost": StatisticChannel(
        "current_year_grid_cost_gross_eur",
        None,
        "EUR",
        has_sum=False,
    ),
    "current_year_solar_cost": StatisticChannel(
        "current_year_solar_cost_gross_eur",
        None,
        "EUR",
        has_sum=False,
    ),
    "current_year_total_cost": StatisticChannel(
        "current_year_total_cost_gross_eur",
        None,
        "EUR",
        has_sum=False,
    ),
    "imported_energy": StatisticChannel(
        "grid_kwh_total",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        max_hourly_delta=True,
    ),
    "solar_energy": StatisticChannel(
        "solar_kwh_total",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        max_hourly_delta=True,
    ),
    "total_energy": StatisticChannel(
        "total_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        max_hourly_delta=True,
    ),
    "raw_grid_energy": StatisticChannel(
        "raw_grid_kwh_total",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        max_hourly_delta=True,
    ),
    "current_month_grid_energy": StatisticChannel(
        "current_month_grid_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        allow_reset=True,
    ),
    "current_month_solar_energy": StatisticChannel(
        "current_month_solar_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        allow_reset=True,
    ),
    "current_month_total_energy": StatisticChannel(
        "current_month_total_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        allow_reset=True,
    ),
    "current_year_grid_energy": StatisticChannel(
        "current_year_grid_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        allow_reset=True,
    ),
    "current_year_solar_energy": StatisticChannel(
        "current_year_solar_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        allow_reset=True,
    ),
    "current_year_total_energy": StatisticChannel(
        "current_year_total_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        allow_reset=True,
    ),
    "current_year_raw_grid_energy": StatisticChannel(
        "current_year_raw_grid_kwh",
        EnergyConverter.UNIT_CLASS,
        UnitOfEnergy.KILO_WATT_HOUR,
        allow_reset=True,
    ),
    "grid_price": StatisticChannel(
        "grid_price_gross_eur_per_kwh",
        None,
        "EUR/kWh",
        has_sum=False,
        has_mean=True,
    ),
    "solar_price": StatisticChannel(
        "solar_price_gross_eur_per_kwh",
        None,
        "EUR/kWh",
        has_sum=False,
        has_mean=True,
    ),
    "tax_rate": StatisticChannel(
        "tax_rate",
        None,
        "%",
        has_sum=False,
        has_mean=True,
        value_multiplier=100.0,
    ),
    "autarky": StatisticChannel("autarky_percent", None, "%", has_sum=False, has_mean=True),
    "pv_co2_savings": StatisticChannel(
        "pv_co2_savings_t", None, "t", has_sum=False, has_mean=True
    ),
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
    state_start: float | None = None,
    max_hourly_delta: float | None = None,
    allow_reset: bool = False,
) -> list[dict]:
    """Convert cumulative meter readings to recorder statistics rows."""
    rows_by_start = {}
    previous_total: float | None = state_start
    previous_timestamp: datetime | None = None
    current_sum = sum_start
    for reading in sorted(
        readings,
        key=lambda item: (item.timestamp or dt_util.utcnow(), item.meter_id),
    ):
        total = getattr(reading, value_attr)
        if reading.timestamp is None or total is None:
            continue
        timestamp = dt_util.as_utc(reading.timestamp)
        start = _statistics_hour_start(timestamp) if align_to_hour else timestamp
        if total < 0:
            _LOGGER.warning(
                "Skipping Astra negative statistic attr=%s start=%s current=%s",
                value_attr,
                start,
                total,
            )
            continue
        if previous_total is not None:
            delta = total - previous_total
            if delta < 0:
                if allow_reset:
                    current_sum += total
                    previous_total = total
                    previous_timestamp = timestamp
                    rows_by_start[start] = {
                        "start": start,
                        "state": total,
                        "sum": current_sum,
                    }
                    continue
                _LOGGER.warning(
                    "Skipping Astra statistic rollback attr=%s start=%s previous=%s current=%s",
                    value_attr,
                    start,
                    previous_total,
                    total,
                )
                continue
            if max_hourly_delta is not None and previous_timestamp is not None:
                elapsed_hours = max(
                    (timestamp - previous_timestamp).total_seconds() / 3600,
                    0.25,
                )
                if delta > max_hourly_delta * elapsed_hours:
                    _LOGGER.warning(
                        "Skipping Astra statistic spike attr=%s start=%s delta=%s limit=%s",
                        value_attr,
                        start,
                        delta,
                        max_hourly_delta * elapsed_hours,
                    )
                    continue
            current_sum += delta
        previous_total = total
        previous_timestamp = timestamp
        rows_by_start[start] = {
            "start": start,
            "state": total,
            "sum": current_sum,
        }
    return list(rows_by_start.values())


def _statistics_state_rows(
    readings: list[AstraMeterReading],
    value_attr: str,
    *,
    align_to_hour: bool = False,
    value_multiplier: float = 1.0,
) -> list[dict]:
    """Convert point-in-time readings to state-only recorder statistics rows."""
    rows_by_start = {}
    for reading in sorted(
        readings,
        key=lambda item: (item.timestamp or dt_util.utcnow(), item.meter_id),
    ):
        value = getattr(reading, value_attr)
        if reading.timestamp is None or value is None:
            continue
        value *= value_multiplier
        timestamp = dt_util.as_utc(reading.timestamp)
        start = _statistics_hour_start(timestamp) if align_to_hour else timestamp
        rows_by_start[start] = {
            "start": start,
            "state": value,
            "sum": None,
        }
    return list(rows_by_start.values())


def _statistics_mean_rows(
    readings: list[AstraMeterReading],
    value_attr: str,
    *,
    align_to_hour: bool = False,
    value_multiplier: float = 1.0,
) -> list[dict]:
    """Convert point-in-time readings to mean recorder statistics rows."""
    rows_by_start = {}
    for reading in sorted(
        readings,
        key=lambda item: (item.timestamp or dt_util.utcnow(), item.meter_id),
    ):
        value = getattr(reading, value_attr)
        if reading.timestamp is None or value is None:
            continue
        value *= value_multiplier
        timestamp = dt_util.as_utc(reading.timestamp)
        start = _statistics_hour_start(timestamp) if align_to_hour else timestamp
        rows_by_start[start] = {
            "start": start,
            "mean": value,
        }
    return list(rows_by_start.values())


def _batches(items: list, size: int) -> list[list]:
    """Split a list into bounded batches for recorder imports."""
    return [items[index : index + size] for index in range(0, len(items), size)]


def _statistic_data(StatisticData, row: dict):
    """Build Home Assistant StatisticData with only populated fields."""
    kwargs = {"start": row["start"]}
    for key in ("state", "sum", "mean"):
        if key in row:
            kwargs[key] = row[key]
    return StatisticData(**kwargs)


async def _async_statistic_starts(
    hass: HomeAssistant,
    statistic_ids: set[str],
    start: datetime,
) -> dict[str, dict[str, float]]:  # pragma: no cover
    """Return recorder sum and state immediately before the imported window."""
    query_start = start - timedelta(days=3650)

    def read_starts() -> dict[str, dict[str, float]]:
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
            {"state", "sum"},
        )
        starts = {}
        for statistic_id, rows in result.items():
            for row in reversed(rows):
                state = row.get("state")
                total_sum = row.get("sum")
                if state is not None or total_sum is not None:
                    starts[statistic_id] = {}
                    if state is not None:
                        starts[statistic_id]["state"] = state
                    if total_sum is not None:
                        starts[statistic_id]["sum"] = total_sum
                    break
        return starts

    try:
        from homeassistant.components.recorder import get_instance
    except ImportError:
        return await hass.async_add_executor_job(read_starts)

    return await get_instance(hass).async_add_executor_job(read_starts)


async def _async_sum_starts(
    hass: HomeAssistant,
    statistic_ids: set[str],
    start: datetime,
) -> dict[str, float]:  # pragma: no cover
    """Return recorder sums immediately before the imported window."""
    starts = await _async_statistic_starts(hass, statistic_ids, start)
    return {
        statistic_id: values["sum"]
        for statistic_id, values in starts.items()
        if "sum" in values
    }


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
    statistic_starts = await _async_statistic_starts(hass, statistic_ids, start)

    for meter_id, meter_readings in grouped.items():
        if not meter_readings:
            continue
        for channel, channel_def in STATISTIC_CHANNELS.items():
            statistic_id = _sensor_statistic_id(meter_readings[-1], channel)
            metadata = StatisticMetaData(
                has_sum=channel_def.has_sum,
                mean_type=(
                    StatisticMeanType.ARITHMETIC
                    if channel_def.has_mean
                    else StatisticMeanType.NONE
                ),
                name=SENSOR_DISPLAY_NAMES[channel],
                source=RECORDER_SOURCE,
                statistic_id=statistic_id,
                unit_class=channel_def.unit_class,
                unit_of_measurement=channel_def.unit_of_measurement,
            )
            row_dicts = (
                _statistics_rows(
                    meter_readings,
                    channel_def.value_attr,
                    align_to_hour=history_granularity == HISTORY_GRANULARITY_QUARTER_HOUR,
                    sum_start=statistic_starts.get(statistic_id, {}).get("sum", 0.0),
                    state_start=statistic_starts.get(statistic_id, {}).get("state"),
                    allow_reset=channel_def.allow_reset,
                    max_hourly_delta=(
                        coordinator.config_entry.options.get(
                            CONF_MAX_INTERVAL_AVERAGE_KW,
                            DEFAULT_MAX_INTERVAL_AVERAGE_KW,
                        )
                        if channel_def.max_hourly_delta
                        else None
                    ),
                )
                if channel_def.has_sum
                else _statistics_mean_rows(
                    meter_readings,
                    channel_def.value_attr,
                    align_to_hour=history_granularity == HISTORY_GRANULARITY_QUARTER_HOUR,
                    value_multiplier=channel_def.value_multiplier,
                )
                if channel_def.has_mean
                else _statistics_state_rows(
                    meter_readings,
                    channel_def.value_attr,
                    align_to_hour=history_granularity == HISTORY_GRANULARITY_QUARTER_HOUR,
                    value_multiplier=channel_def.value_multiplier,
                )
            )
            rows = [
                _statistic_data(StatisticData, row)
                for row in row_dicts
            ]
            if rows:
                try:
                    imported_rows = 0
                    for batch in _batches(rows, STATISTIC_IMPORT_BATCH_SIZE):
                        async_import_statistics(hass, metadata, batch)
                        imported_rows += len(batch)
                        await asyncio.sleep(0)
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
                    imported_rows,
                    statistic_id,
                )
    await async_delete_issue(hass, ISSUE_BACKFILL_FAILED)
    return {meter_id: len(meter_readings) for meter_id, meter_readings in grouped.items()}
