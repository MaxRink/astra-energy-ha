"""Long-term statistics import helpers for Astra Energy."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api import AstraMeterReading
from .const import (
    HISTORY_GRANULARITY_MONTHLY,
    HISTORY_GRANULARITY_QUARTER_HOUR,
    ISSUE_BACKFILL_FAILED,
)
from .coordinator import AstraEnergyCoordinator
from .reporting import async_create_issue, async_delete_issue, summarize_counts

_LOGGER = logging.getLogger(__name__)

RECORDER_SOURCE = "recorder"

STATISTIC_CHANNELS = {
    "imported_energy": ("grid energy", "grid_kwh_total"),
    "solar_energy": ("solar energy", "solar_kwh_total"),
    "total_energy": ("total energy", "total_kwh"),
}


def _sensor_statistic_id(reading: AstraMeterReading, channel: str) -> str:
    """Return the entity statistic id used by the energy sensor."""
    return f"sensor.astra_energy_{reading.meter_id}_{channel}"


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
) -> list[dict]:
    """Convert cumulative meter readings to recorder statistics rows."""
    rows_by_start = {}
    for reading in sorted(
        readings,
        key=lambda item: (item.timestamp or dt_util.utcnow(), item.meter_id),
    ):
        total = getattr(reading, value_attr)
        if reading.timestamp is None or total is None:
            continue
        timestamp = dt_util.as_utc(reading.timestamp)
        start = _statistics_hour_start(timestamp) if align_to_hour else timestamp
        rows_by_start[start] = {
            "start": start,
            "state": total,
            "sum": total,
        }
    return list(rows_by_start.values())


async def async_backfill_statistics(
    hass: HomeAssistant,
    coordinator: AstraEnergyCoordinator,
    *,
    days: int,
    recent_refresh_hours: int,
    history_granularity: str,
    import_statistics: bool,
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
        readings = await coordinator.client.async_get_historical_interval_meter_stands(
            start,
            end,
        )
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

    for meter_id, meter_readings in grouped.items():
        if not meter_readings:
            continue
        name = meter_readings[-1].meter_name
        for channel, (label, value_attr) in STATISTIC_CHANNELS.items():
            statistic_id = _sensor_statistic_id(meter_readings[-1], channel)
            metadata = StatisticMetaData(
                has_sum=True,
                mean_type=StatisticMeanType.NONE,
                name=f"Astra Energy {name} {label}",
                source=RECORDER_SOURCE,
                statistic_id=statistic_id,
                unit_class=EnergyConverter.UNIT_CLASS,
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            rows = [
                StatisticData(start=row["start"], state=row["state"], sum=row["sum"])
                for row in _statistics_rows(
                    meter_readings,
                    value_attr,
                    align_to_hour=history_granularity == HISTORY_GRANULARITY_QUARTER_HOUR,
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
