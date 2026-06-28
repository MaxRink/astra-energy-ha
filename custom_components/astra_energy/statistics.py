"""Long-term statistics import helpers for Astra Energy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api import AstraApiError, AstraAuthError, AstraDeferredDataError, AstraMeterReading
from .const import (
    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
    CONF_GRID_PRICE_NET,
    HISTORY_GRANULARITY_MONTHLY,
    HISTORY_GRANULARITY_QUARTER_HOUR,
    CONF_CACHE_INTERVAL_PAYLOADS,
    CONF_MAX_INTERVAL_AVERAGE_KW,
    CONF_SMOOTH_INTERVAL_ANOMALIES,
    CONF_SMOOTHING_LOOKAROUND_DAYS,
    CONF_SOLAR_PRICE_NET,
    CONF_TAX_RATE,
    DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
    DEFAULT_CACHE_INTERVAL_PAYLOADS,
    DEFAULT_GRID_PRICE_NET,
    DEFAULT_MAX_INTERVAL_AVERAGE_KW,
    DEFAULT_SMOOTH_INTERVAL_ANOMALIES,
    DEFAULT_SMOOTHING_LOOKAROUND_DAYS,
    DEFAULT_SOLAR_PRICE_NET,
    DEFAULT_TAX_RATE,
    ISSUE_BACKFILL_FAILED,
    SENSOR_DISPLAY_NAMES,
    SENSOR_OBJECT_IDS,
)
from .coordinator import AstraEnergyCoordinator, _meter_id_from_entity_registry
from .reporting import async_create_issue, async_delete_issue, summarize_counts

_LOGGER = logging.getLogger(__name__)

RECORDER_SOURCE = "recorder"
INTERVAL_CACHE_STORAGE_KEY = "astra_energy.interval_payload_cache"
INTERVAL_CACHE_STORAGE_VERSION = 1
STATISTIC_IMPORT_BATCH_SIZE = 50

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
    "grid_energy_cost_total": StatisticChannel(
        "grid_cost_total_gross_eur",
        None,
        "EUR",
    ),
    "solar_energy_cost_total": StatisticChannel(
        "solar_cost_total_gross_eur",
        None,
        "EUR",
    ),
    "total_energy_cost_total": StatisticChannel(
        "total_cost_total_gross_eur",
        None,
        "EUR",
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


def _statistic_channels_for_granularity(
    history_granularity: str,
) -> dict[str, StatisticChannel]:
    """Return channels that are valid for a backfill granularity."""
    return STATISTIC_CHANNELS


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
    skipped_negative = 0
    skipped_rollback = 0
    skipped_spike = 0
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
            skipped_negative += 1
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
                previous_timestamp = timestamp
                skipped_rollback += 1
                continue
            if max_hourly_delta is not None and previous_timestamp is not None:
                elapsed_hours = max(
                    (timestamp - previous_timestamp).total_seconds() / 3600,
                    0.25,
                )
                if delta > max_hourly_delta * elapsed_hours:
                    rows_by_start[start] = {
                        "start": start,
                        "state": previous_total,
                        "sum": current_sum,
                    }
                    previous_timestamp = timestamp
                    skipped_spike += 1
                    continue
            current_sum += delta
        previous_total = total
        previous_timestamp = timestamp
        rows_by_start[start] = {
            "start": start,
            "state": total,
            "sum": current_sum,
        }
    if skipped_negative or skipped_rollback or skipped_spike:
        _LOGGER.warning(
            "Skipped Astra statistic rows attr=%s negative=%s rollback=%s spike=%s",
            value_attr,
            skipped_negative,
            skipped_rollback,
            skipped_spike,
        )
    return list(rows_by_start.values())


def _nondecreasing_statistics_rows(
    rows: list[dict],
    *,
    value_attr: str,
    state_start: float | None,
    sum_start: float | None,
) -> list[dict]:
    """Drop recorder rows that would move a cumulative statistic backwards."""
    filtered: list[dict] = []
    previous_state = state_start
    previous_sum = sum_start
    dropped_state = 0
    dropped_sum = 0
    for row in rows:
        state = row.get("state")
        total_sum = row.get("sum")
        if (
            previous_state is not None
            and state is not None
            and state < previous_state
        ):
            dropped_state += 1
            continue
        if (
            previous_sum is not None
            and total_sum is not None
            and total_sum < previous_sum
        ):
            dropped_sum += 1
            continue
        filtered.append(row)
        if state is not None:
            previous_state = state
        if total_sum is not None:
            previous_sum = total_sum
    if dropped_state or dropped_sum:
        _LOGGER.warning(
            "Dropped Astra statistic import rows attr=%s lower_state=%s lower_sum=%s",
            value_attr,
            dropped_state,
            dropped_sum,
        )
    return filtered


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


def _statistic_import_start(
    readings: list[AstraMeterReading],
    value_attr: str,
    *,
    align_to_hour: bool = False,
) -> datetime | None:
    """Return the first recorder bucket that will be written for a channel."""
    starts = []
    for reading in readings:
        if reading.timestamp is None or getattr(reading, value_attr) is None:
            continue
        timestamp = dt_util.as_utc(reading.timestamp)
        starts.append(_statistics_hour_start(timestamp) if align_to_hour else timestamp)
    return min(starts) if starts else None


def _statistic_import_end(
    readings: list[AstraMeterReading],
    value_attr: str,
    *,
    align_to_hour: bool = False,
) -> datetime | None:
    """Return the last recorder bucket that will be written for a channel."""
    starts = []
    for reading in readings:
        if reading.timestamp is None or getattr(reading, value_attr) is None:
            continue
        timestamp = dt_util.as_utc(reading.timestamp)
        starts.append(_statistics_hour_start(timestamp) if align_to_hour else timestamp)
    return max(starts) if starts else None


def _statistic_bucket(
    reading: AstraMeterReading,
    value_attr: str,
    *,
    align_to_hour: bool,
) -> datetime | None:
    """Return the recorder bucket for one reading/value pair."""
    if reading.timestamp is None or getattr(reading, value_attr) is None:
        return None
    timestamp = dt_util.as_utc(reading.timestamp)
    return _statistics_hour_start(timestamp) if align_to_hour else timestamp


def _readings_after_existing_start(
    readings: list[AstraMeterReading],
    value_attr: str,
    *,
    existing_start: datetime,
    existing_state: float | None,
    align_to_hour: bool,
) -> list[AstraMeterReading]:
    """Return readings after an existing recorder row, rebased to its state."""
    anchor_value: float | None = None
    after: list[AstraMeterReading] = []
    for reading in sorted(
        readings,
        key=lambda item: (item.timestamp or dt_util.utcnow(), item.meter_id),
    ):
        bucket = _statistic_bucket(reading, value_attr, align_to_hour=align_to_hour)
        value = getattr(reading, value_attr)
        if bucket is None or value is None:
            continue
        if bucket <= existing_start:
            anchor_value = value
            continue
        after.append(reading)
    if existing_state is None or anchor_value is None:
        return after
    offset = existing_state - anchor_value
    if abs(offset) < 0.000000001:
        return after
    return [
        replace(reading, **{value_attr: getattr(reading, value_attr) + offset})
        for reading in after
        if getattr(reading, value_attr) is not None
    ]


def _statistic_start_from_rows(
    rows: list[dict[str, Any]],
    *,
    require_sum: bool = False,
) -> dict[str, Any]:
    """Return the newest usable recorder state/sum from statistic rows."""
    for row in reversed(rows):
        state = row.get("state")
        total_sum = row.get("sum")
        if require_sum and total_sum is None:
            continue
        if state is not None or total_sum is not None:
            start = {}
            if state is not None:
                start["state"] = state
            if total_sum is not None:
                start["sum"] = total_sum
            if row.get("start") is not None:
                start["start"] = row["start"]
            return start
    return {}


async def _async_statistic_starts(
    hass: HomeAssistant,
    statistic_ids: set[str],
    start: datetime,
    *,
    require_sum: bool = False,
) -> dict[str, dict[str, Any]]:  # pragma: no cover
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
            statistic_start = _statistic_start_from_rows(rows, require_sum=require_sum)
            if statistic_start:
                starts[statistic_id] = statistic_start
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
    starts = await _async_statistic_starts(hass, statistic_ids, start, require_sum=True)
    return {
        statistic_id: values["sum"]
        for statistic_id, values in starts.items()
        if "sum" in values
    }


async def _async_interval_start_baseline(
    hass: HomeAssistant,
    coordinator: AstraEnergyCoordinator,
    start: datetime,
    end: datetime,
) -> AstraMeterReading | None:
    """Return a recorder-backed cumulative baseline for interval-only imports."""
    template = next(iter((coordinator.data or {}).values()), None)
    meter_id = template.meter_id if template is not None else _meter_id_from_entity_registry(hass)
    if meter_id is None:
        return None
    statistic_ids = {
        f"sensor.{SENSOR_OBJECT_IDS[channel]}"
        for channel in ("imported_energy", "solar_energy", "total_energy", "raw_grid_energy")
    }
    states = await _async_statistic_starts(
        hass,
        statistic_ids,
        start,
    )
    grid_state = states.get(f"sensor.{SENSOR_OBJECT_IDS['imported_energy']}", {})
    solar_state = states.get(f"sensor.{SENSOR_OBJECT_IDS['solar_energy']}", {})
    total_state = states.get(f"sensor.{SENSOR_OBJECT_IDS['total_energy']}", {})
    raw_grid_state = states.get(f"sensor.{SENSOR_OBJECT_IDS['raw_grid_energy']}", {})
    grid = grid_state.get("state")
    solar = solar_state.get("state")
    total = total_state.get("state")
    raw_grid = raw_grid_state.get("state")
    if total is None and (grid is not None or solar is not None):
        total = (grid or 0.0) + (solar or 0.0)
    if grid is None and total is not None and solar is not None:
        grid = max(total - solar, 0.0)
    if all(value is None for value in (grid, solar, total)):
        return None
    start_rows = [
        row_start
        for row_start in (
            grid_state.get("start"),
            solar_state.get("start"),
            total_state.get("start"),
            raw_grid_state.get("start"),
        )
        if isinstance(row_start, datetime)
    ]
    baseline_timestamp = max(start_rows) + timedelta(hours=1) if start_rows else start
    baseline_timestamp = min(max(baseline_timestamp, start), end)
    options = coordinator.config_entry.options
    grid_price_net = (
        template.grid_price_net_eur_per_kwh
        if template is not None and template.grid_price_net_eur_per_kwh is not None
        else float(options.get(CONF_GRID_PRICE_NET, DEFAULT_GRID_PRICE_NET))
    )
    solar_price_net = (
        template.solar_price_net_eur_per_kwh
        if template is not None and template.solar_price_net_eur_per_kwh is not None
        else float(options.get(CONF_SOLAR_PRICE_NET, DEFAULT_SOLAR_PRICE_NET))
    )
    tax_rate = (
        template.tax_rate
        if template is not None and template.tax_rate is not None
        else float(options.get(CONF_TAX_RATE, DEFAULT_TAX_RATE))
    )
    return AstraMeterReading(
        meter_id=meter_id,
        meter_name=template.meter_name if template is not None else "Astra Energy Meter",
        timestamp=baseline_timestamp,
        power_w=None,
        imported_kwh_total=grid,
        grid_kwh_total=grid,
        solar_kwh_total=solar,
        total_kwh=total,
        unsmoothed_grid_kwh_total=grid,
        unsmoothed_solar_kwh_total=solar,
        unsmoothed_total_kwh=total,
        raw_grid_kwh_total=raw_grid if raw_grid is not None else grid,
        grid_price_net_eur_per_kwh=grid_price_net,
        grid_price_gross_eur_per_kwh=grid_price_net * (1 + tax_rate),
        solar_price_net_eur_per_kwh=solar_price_net,
        solar_price_gross_eur_per_kwh=solar_price_net * (1 + tax_rate),
        tax_rate=tax_rate,
        raw={
            "source": "recorder_interval_start_baseline",
            "requested_start": start.isoformat(),
            "baseline_timestamp": baseline_timestamp.isoformat(),
        },
    )


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
        start_baseline = await _async_interval_start_baseline(
            hass,
            coordinator,
            start,
            end,
        )
        interval_start = (
            max(start, start_baseline.timestamp)
            if start_baseline is not None and start_baseline.timestamp is not None
            else start
        )
        try:
            end_template = next(iter((coordinator.data or {}).values()), None)
            readings = await coordinator.client.async_get_historical_interval_meter_stands(
                interval_start,
                end,
                start_baseline=start_baseline,
                end_template=end_template,
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
        except AstraAuthError:
            raise
        except AstraDeferredDataError as err:
            _LOGGER.warning("Astra historical interval import deferred: %s", err)
            await async_delete_issue(hass, ISSUE_BACKFILL_FAILED)
            return {}
        except AstraApiError as err:
            _LOGGER.warning("Astra historical interval import deferred: %s", err)
            await async_create_issue(
                hass,
                ISSUE_BACKFILL_FAILED,
                translation_key=ISSUE_BACKFILL_FAILED,
                placeholders={"error": str(err)},
                notification_title="Astra Energy backfill deferred",
                notification_message=(
                    "Astra Energy could not fetch a valid historical payload. "
                    "No statistics were imported; Home Assistant can retry when "
                    f"Astra returns valid data again. Last error: {err}"
                ),
            )
            return {}
        if use_cache and len(payload_cache) != cache_size_before:
            await _async_save_interval_payload_cache(hass, payload_cache)
    else:
        history_granularity = HISTORY_GRANULARITY_MONTHLY
        try:
            readings = await coordinator.client.async_get_historical_meter_stands(start, end)
        except AstraAuthError:
            raise
        except AstraDeferredDataError as err:
            _LOGGER.warning("Astra historical import deferred: %s", err)
            await async_delete_issue(hass, ISSUE_BACKFILL_FAILED)
            return {}
        except AstraApiError as err:
            _LOGGER.warning("Astra historical import deferred: %s", err)
            await async_create_issue(
                hass,
                ISSUE_BACKFILL_FAILED,
                translation_key=ISSUE_BACKFILL_FAILED,
                placeholders={"error": str(err)},
                notification_title="Astra Energy backfill deferred",
                notification_message=(
                    "Astra Energy could not fetch a valid historical payload. "
                    "No statistics were imported; Home Assistant can retry when "
                    f"Astra returns valid data again. Last error: {err}"
                ),
            )
            return {}
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

    statistic_channels = _statistic_channels_for_granularity(history_granularity)
    statistic_starts: dict[tuple[str, datetime], dict[str, float]] = {}
    rewrite_start = (
        _statistics_hour_start(end - timedelta(hours=recent_refresh_hours))
        if history_granularity == HISTORY_GRANULARITY_QUARTER_HOUR
        and recent_refresh_hours > 0
        else None
    )

    for meter_id, meter_readings in grouped.items():
        if not meter_readings:
            continue
        for channel, channel_def in statistic_channels.items():
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
            align_to_hour = history_granularity == HISTORY_GRANULARITY_QUARTER_HOUR
            channel_readings = meter_readings
            aligned_import_start = _statistic_import_start(
                meter_readings,
                channel_def.value_attr,
                align_to_hour=align_to_hour,
            )
            aligned_import_end = _statistic_import_end(
                meter_readings,
                channel_def.value_attr,
                align_to_hour=align_to_hour,
            )
            statistic_start = {}
            if (
                channel_def.has_sum
                and aligned_import_start is not None
                and aligned_import_end is not None
            ):
                if rewrite_start is not None and aligned_import_end >= rewrite_start:
                    import_anchor = max(aligned_import_start, rewrite_start)
                    cache_key = (statistic_id, import_anchor)
                    if cache_key not in statistic_starts:
                        starts = await _async_statistic_starts(
                            hass,
                            {statistic_id},
                            import_anchor,
                            require_sum=True,
                        )
                        statistic_starts[cache_key] = starts.get(statistic_id, {})
                    statistic_start = statistic_starts[cache_key]
                    existing_start = statistic_start.get("start")
                    if isinstance(existing_start, datetime):
                        channel_readings = _readings_after_existing_start(
                            meter_readings,
                            channel_def.value_attr,
                            existing_start=existing_start,
                            existing_state=statistic_start.get("state"),
                            align_to_hour=align_to_hour,
                        )
                else:
                    cache_key = (statistic_id, aligned_import_end)
                    if cache_key not in statistic_starts:
                        starts = await _async_statistic_starts(
                            hass,
                            {statistic_id},
                            aligned_import_end + timedelta(microseconds=1),
                            require_sum=True,
                        )
                        statistic_starts[cache_key] = starts.get(statistic_id, {})
                    statistic_start = statistic_starts[cache_key]
                    existing_start = statistic_start.get("start")
                    if (
                        isinstance(existing_start, datetime)
                        and existing_start >= aligned_import_start
                    ):
                        channel_readings = _readings_after_existing_start(
                            meter_readings,
                            channel_def.value_attr,
                            existing_start=existing_start,
                            existing_state=statistic_start.get("state"),
                            align_to_hour=align_to_hour,
                        )
                if not channel_readings:
                    continue
            row_dicts = (
                _statistics_rows(
                    channel_readings,
                    channel_def.value_attr,
                    align_to_hour=align_to_hour,
                    sum_start=statistic_start.get("sum", 0.0),
                    state_start=statistic_start.get("state"),
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
                    channel_readings,
                    channel_def.value_attr,
                    align_to_hour=align_to_hour,
                    value_multiplier=channel_def.value_multiplier,
                )
                if channel_def.has_mean
                else _statistics_state_rows(
                    channel_readings,
                    channel_def.value_attr,
                    align_to_hour=align_to_hour,
                    value_multiplier=channel_def.value_multiplier,
                )
            )
            if channel_def.has_sum:
                row_dicts = _nondecreasing_statistics_rows(
                    row_dicts,
                    value_attr=channel_def.value_attr,
                    state_start=statistic_start.get("state"),
                    sum_start=statistic_start.get("sum"),
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
