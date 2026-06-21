"""Astra API client."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from hashlib import md5
import asyncio
import json
import logging
import re
from time import perf_counter
from typing import TYPE_CHECKING, Any

from .const import (
    DAILY_INTERVAL_CONCURRENCY,
    DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
    DEFAULT_GRID_PRICE_NET,
    DEFAULT_MAX_INTERVAL_AVERAGE_KW,
    DEFAULT_SMOOTH_INTERVAL_ANOMALIES,
    DEFAULT_SMOOTHING_LOOKAROUND_DAYS,
    DEFAULT_SOLAR_PRICE_NET,
    DEFAULT_TAX_RATE,
)

if TYPE_CHECKING:
    from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)


class AstraApiError(Exception):
    """Base Astra API error."""


class AstraAuthError(AstraApiError):
    """Authentication failed or the session expired."""


class AstraApiNotDocumentedError(AstraApiError):
    """Raised until confirmed Astra endpoints are wired in."""


class AstraProtocolError(AstraApiError):
    """Astra returned malformed or unverifiable data."""


@dataclass(frozen=True)
class AstraMeterReading:
    """Latest normalized Astra meter reading."""

    meter_id: str
    meter_name: str
    timestamp: datetime | None
    power_w: float | None
    imported_kwh_total: float | None
    grid_kwh_total: float | None = None
    solar_kwh_total: float | None = None
    total_kwh: float | None = None
    unsmoothed_grid_kwh_total: float | None = None
    unsmoothed_solar_kwh_total: float | None = None
    unsmoothed_total_kwh: float | None = None
    raw_grid_kwh_total: float | None = None
    exported_kwh_total: float | None = None
    cost_total: float | None = None
    currency: str | None = None
    grid_price_net_eur_per_kwh: float | None = None
    grid_price_gross_eur_per_kwh: float | None = None
    solar_price_net_eur_per_kwh: float | None = None
    solar_price_gross_eur_per_kwh: float | None = None
    tax_rate: float | None = None
    current_month_grid_kwh: float | None = None
    current_month_solar_kwh: float | None = None
    current_month_total_kwh: float | None = None
    current_month_raw_grid_kwh: float | None = None
    current_month_grid_cost_gross_eur: float | None = None
    current_month_solar_cost_gross_eur: float | None = None
    current_month_total_cost_gross_eur: float | None = None
    current_year_grid_kwh: float | None = None
    current_year_solar_kwh: float | None = None
    current_year_total_kwh: float | None = None
    current_year_raw_grid_kwh: float | None = None
    current_year_grid_cost_gross_eur: float | None = None
    current_year_solar_cost_gross_eur: float | None = None
    current_year_total_cost_gross_eur: float | None = None
    autarky_percent: float | None = None
    pv_co2_savings_t: float | None = None
    raw_meter_id: str | None = None
    legacy_meter_id: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class AstraAccountInfo:
    """Basic authenticated Astra account information."""

    username: str
    company_id: str | None
    company_name: str | None
    selected_location_id: str | None
    selected_location_name: str | None
    is_tenant: bool


def _md5(value: str) -> str:
    """Return lowercase MD5 hex digest used by Astra's Android API."""
    return md5(value.encode()).hexdigest()


def _checksum(action: str, timestamp: str) -> str:
    """Return Astra request checksum."""
    return _md5(f"SNAFU{action}{timestamp}")


def _session_id(username: str, password: str) -> str:
    """Return Astra Android session id for username/password."""
    return _md5(f"{username}{_md5(password)}")


def _total_or_zero(value: float | None) -> float:
    """Return a cumulative meter value or zero when Astra omitted it."""
    return value if value is not None else 0.0


def _round_or_none(value: float | None, digits: int = 6) -> float | None:
    """Round a numeric value while preserving missing data."""
    return round(value, digits) if value is not None else None


def _cost_gross(kwh: float | None, price_gross: float | None) -> float | None:
    """Return gross cost for an energy amount and price."""
    if kwh is None or price_gross is None:
        return None
    return round(kwh * price_gross, 4)


def _parse_number(value: Any) -> float | None:
    """Parse German/English number strings into floats."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    """Parse common Astra date strings."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _normalize_identifier(value: Any) -> str | None:
    """Return a Home Assistant-safe identifier value."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", text).strip("_") or None


def _raw_meter_id_from_row(row: dict[str, Any]) -> str | None:
    """Extract the raw Astra meter identifier when the API exposes one."""
    preferred_keys = (
        "meter_id",
        "meterId",
        "zaehler_id",
        "zaehlerId",
        "zähler_id",
        "zaehlernummer",
        "zählernummer",
        "zaehler_nr",
        "zähler_nr",
        "serial",
        "serial_number",
        "geraet",
        "gerät",
        "device",
        "prnr",
        "prnr1",
        "id",
        "mtr_id",
        "mtrid",
    )
    for key in preferred_keys:
        raw_id = _normalize_identifier(row.get(key))
        if raw_id:
            return raw_id
    label = str(row.get("v01") or "").strip()
    if re.search(r"\d", label) and not re.search(r"\s", label):
        return _normalize_identifier(label)
    return None


def _derived_meter_id(*parts: str) -> str:
    """Return a stable fallback meter id when Astra omits a raw id."""
    return f"derived_{_md5('|'.join(parts))[:16]}"


def _raw_payload_without_ids(row: dict[str, Any]) -> dict[str, Any]:
    """Return row data with sensitive/high-cardinality identifiers removed."""
    return {
        key: value
        for key, value in row.items()
        if key.lower()
        not in {
            "id",
            "meter_id",
            "meterid",
            "zaehler_id",
            "zähler_id",
            "zaehlernummer",
            "zählernummer",
            "serial",
            "serial_number",
            "prnr",
            "prnr1",
            "mtr_id",
            "mtrid",
        }
    }


def _meter_channel_kind(meter_name: str, medium: str, account: str) -> str:
    """Classify one Astra meter row as total, grid, solar/object, or generic."""
    text = f"{meter_name} {medium} {account}".casefold()
    if "netzbezug" in text or "netzstrom" in text or " t1" in text or "zt1" in text:
        return "grid"
    if (
        "objektbezug" in text
        or "objektstrom" in text
        or "pv" in text
        or " t2" in text
        or "zt2" in text
    ):
        return "solar"
    if "vgb" in text or ("strom" in text and "netz" not in text and "objekt" not in text):
        return "total"
    return "generic"


def _reading_from_channel(channel: dict[str, Any]) -> AstraMeterReading:
    """Build a reading from one ungrouped channel row."""
    meter_id = channel["raw_meter_id"] or channel["legacy_meter_id"]
    total = channel["total"]
    return AstraMeterReading(
        meter_id=meter_id,
        meter_name=channel["meter_name"],
        timestamp=channel["timestamp"],
        power_w=None,
        imported_kwh_total=total,
        grid_kwh_total=total,
        total_kwh=total,
        unsmoothed_grid_kwh_total=total,
        unsmoothed_total_kwh=total,
        raw_meter_id=channel["raw_meter_id"],
        legacy_meter_id=channel["legacy_meter_id"],
        raw={
            "action": "get_mtr_lzs",
            "unit": channel["unit"],
            "interval_consumption": channel["interval_consumption"],
            "medium": channel["medium"],
            "account": channel["account"],
            "row": channel["row"],
        },
    )


def _combined_reading_from_channels(channels: list[dict[str, Any]]) -> AstraMeterReading:
    """Build one logical meter reading from Astra's total/grid/PV rows."""
    total_channel = _first_channel(channels, "total") or channels[0]
    grid_channel = _first_channel(channels, "grid")
    solar_channel = _first_channel(channels, "solar")
    timestamps = [channel["timestamp"] for channel in channels if channel["timestamp"]]
    raw_meter_id = total_channel["raw_meter_id"]
    legacy_meter_id = _derived_meter_id(
        total_channel["meter_name"],
        total_channel["medium"],
        total_channel["account"],
    )
    meter_id = raw_meter_id or legacy_meter_id
    solar_total = solar_channel["total"] if solar_channel else None
    total_kwh = total_channel["total"]
    raw_grid_total = grid_channel["total"] if grid_channel else None
    grid_total = (
        max(total_kwh - solar_total, 0.0)
        if solar_total is not None
        else raw_grid_total or total_kwh
    )
    return AstraMeterReading(
        meter_id=meter_id,
        meter_name=total_channel["meter_name"],
        timestamp=max(timestamps) if timestamps else None,
        power_w=None,
        imported_kwh_total=grid_total,
        grid_kwh_total=grid_total,
        solar_kwh_total=solar_total,
        total_kwh=total_kwh,
        unsmoothed_grid_kwh_total=grid_total,
        unsmoothed_solar_kwh_total=solar_total,
        unsmoothed_total_kwh=total_kwh,
        raw_grid_kwh_total=raw_grid_total,
        raw_meter_id=raw_meter_id,
        legacy_meter_id=legacy_meter_id,
        raw={
            "action": "get_mtr_lzs",
            "grid_source": "derived_total_minus_solar"
            if solar_total is not None
            else "raw_grid_or_total",
            "raw_grid_kwh_total": raw_grid_total,
            "channels": {
                channel["kind"]: {
                    "raw_meter_id": channel["raw_meter_id"],
                    "legacy_meter_id": channel["legacy_meter_id"],
                    "meter_name": channel["meter_name"],
                    "medium": channel["medium"],
                    "account": channel["account"],
                    "unit": channel["unit"],
                    "interval_consumption": channel["interval_consumption"],
                    "row": channel["row"],
                }
                for channel in channels
            },
        },
    )


def _first_channel(channels: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    """Return the first channel with a matching kind."""
    return next((channel for channel in channels if channel["kind"] == kind), None)


def _iter_months(start: date, end: date) -> list[tuple[int, int]]:
    """Return unique year/month pairs between two dates inclusive."""
    months: list[tuple[int, int]] = []
    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return months


def _iter_days(start: date, end: date) -> list[date]:
    """Return dates between start and end inclusive."""
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _first_day_of_month(value: date) -> date:
    """Return the first day of the month containing value."""
    return value.replace(day=1)


def _previous_month(value: date) -> date:
    """Return the first day of the month before value."""
    first = _first_day_of_month(value)
    if first.month == 1:
        return date(first.year - 1, 12, 1)
    return date(first.year, first.month - 1, 1)


def _combine_utc(day: date) -> datetime:
    """Return a UTC midnight datetime for a date."""
    return datetime.combine(day, time.min, tzinfo=UTC)


def _split_csv_text(value: Any) -> list[str]:
    """Split Astra's comma-separated label/title strings."""
    if not value or str(value).strip() == "0":
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _split_15m_series(value: Any) -> list[list[float]]:
    """Split Astra's semicolon/comma-separated 15-minute series values."""
    if not value or str(value).strip() == "0":
        return []
    result: list[list[float]] = []
    for part in str(value).split(";"):
        points = []
        for item in part.split(","):
            parsed = _parse_number(item)
            if parsed is not None:
                points.append(parsed)
        result.append(points)
    return result


def _series_value(series: dict[str, list[float]], name: str, index: int) -> float | None:
    """Return one point from a named 15-minute series."""
    values = series.get(name.casefold())
    if not values or index >= len(values):
        return None
    return values[index]


def _redistribution_weights(
    points: list[dict[str, Any]],
    indexes: list[int],
    weight_keys: tuple[str, ...],
    *,
    key: str,
    lookaround_days: int,
) -> list[float]:
    """Return normalized weights for redistributing a delayed interval value."""
    if lookaround_days > 0:
        profile_weights = []
        for index in indexes:
            timestamp = points[index]["timestamp"]
            bucket_weight = 0.0
            for other in points:
                if other is points[index] or not other.get("valid", True):
                    continue
                if abs((other["timestamp"].date() - timestamp.date()).days) > lookaround_days:
                    continue
                if other["timestamp"].time() == timestamp.time():
                    bucket_weight += max(float(other.get(key) or 0.0), 0.0)
            profile_weights.append(bucket_weight)
        if any(profile_weights):
            total = sum(profile_weights)
            return [weight / total for weight in profile_weights]
    weights = []
    for index in indexes:
        weight = sum(max(float(points[index].get(key) or 0.0), 0.0) for key in weight_keys)
        weights.append(weight)
    if not any(weights):
        return [1.0 / len(indexes)] * len(indexes)
    total = sum(weights)
    return [weight / total for weight in weights]


def _interval_hour_start(timestamp: datetime) -> datetime:
    """Return the recorder hour bucket for an interval-end timestamp."""
    start = timestamp.replace(minute=0, second=0, microsecond=0)
    if timestamp == start:
        return start - timedelta(hours=1)
    return start


def _redistribute_interval_spikes(
    points: list[dict[str, Any]],
    key: str,
    *,
    max_interval_kwh: float,
    smooth_anomalies: bool,
    redistribution_window: int,
    smoothing_lookaround_days: int,
    report: dict[str, int],
) -> None:
    """Redistribute implausible delayed values over preceding flat buckets."""
    weight_keys = ("solar_kwh",) if key == "total_kwh" else ("total_kwh",)
    delayed_catchup_min_kwh = max(1.0, max_interval_kwh / 4.0)
    for index, point in enumerate(points):
        value = float(point.get(key) or 0.0)
        hard_spike = value > max_interval_kwh
        if not hard_spike and (
            not smooth_anomalies or value <= delayed_catchup_min_kwh
        ):
            continue
        start = index
        while start > 0 and index - start < redistribution_window:
            previous = float(points[start - 1].get(key) or 0.0)
            if previous > 0.001:
                break
            start -= 1
        indexes = list(range(start, index + 1))
        if not hard_spike and len(indexes) < 3:
            continue
        if not smooth_anomalies or len(indexes) <= 1:
            point["valid"] = False
            point.setdefault("anomalies", []).append(f"{key}_spike")
            report[f"{key}_rejected"] = report.get(f"{key}_rejected", 0) + 1
            continue
        weights = _redistribution_weights(
            points,
            indexes,
            weight_keys,
            key=key,
            lookaround_days=smoothing_lookaround_days,
        )
        for target_index, weight in zip(indexes, weights, strict=False):
            points[target_index][key] = value * weight
        reason = "redistributed" if hard_spike else "catchup_redistributed"
        report[f"{key}_{reason}"] = report.get(f"{key}_{reason}", 0) + 1
        report[f"{key}_redistributed_buckets"] = (
            report.get(f"{key}_redistributed_buckets", 0) + len(indexes)
        )


def _sanitize_interval_points(
    points: list[dict[str, Any]],
    *,
    max_average_kw: float = DEFAULT_MAX_INTERVAL_AVERAGE_KW,
    smooth_anomalies: bool = DEFAULT_SMOOTH_INTERVAL_ANOMALIES,
    redistribution_window: int = DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
    smoothing_lookaround_days: int = DEFAULT_SMOOTHING_LOOKAROUND_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reject or smooth impossible interval values before cumulative import."""
    sanitized = [{**point} for point in sorted(points, key=lambda item: item["timestamp"])]
    report: dict[str, int] = {}
    max_interval_kwh = max_average_kw / 4.0
    for point in sanitized:
        point["valid"] = True
        for key in ("total_kwh", "solar_kwh"):
            value = float(point.get(key) or 0.0)
            if value < 0:
                point[key] = None
                point["valid"] = False
                point.setdefault("anomalies", []).append(f"{key}_negative")
                report[f"{key}_negative_rejected"] = (
                    report.get(f"{key}_negative_rejected", 0) + 1
                )
    for key in ("total_kwh", "solar_kwh"):
        _redistribute_interval_spikes(
            sanitized,
            key,
            max_interval_kwh=max_interval_kwh,
            smooth_anomalies=smooth_anomalies,
            redistribution_window=redistribution_window,
            smoothing_lookaround_days=smoothing_lookaround_days,
            report=report,
        )
    for point in sanitized:
        if not point.get("valid", True):
            continue
        total = max(float(point.get("total_kwh") or 0.0), 0.0)
        solar = max(float(point.get("solar_kwh") or 0.0), 0.0)
        if solar > total:
            solar = total
            point["solar_kwh"] = solar
            report["solar_kwh_clamped_to_total"] = report.get("solar_kwh_clamped_to_total", 0) + 1
        point["grid_kwh"] = max(total - solar, 0.0)
        if point["grid_kwh"] > max_interval_kwh:
            point["valid"] = False
            point.setdefault("anomalies", []).append("grid_kwh_spike")
            report["grid_kwh_capped"] = report.get("grid_kwh_capped", 0) + 1
    return sanitized, report


def _daily_interval_values_and_report_from_payload(
    data: dict[str, Any],
    day: date,
    *,
    max_average_kw: float = DEFAULT_MAX_INTERVAL_AVERAGE_KW,
    smooth_anomalies: bool = DEFAULT_SMOOTH_INTERVAL_ANOMALIES,
    redistribution_window: int = DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
    smoothing_lookaround_days: int = DEFAULT_SMOOTHING_LOOKAROUND_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Parse one `get_mtr_eb` daily payload into sanitized 15-minute values."""
    rows = data.get("data") or []
    if not rows or not isinstance(rows[0], dict):
        return [], {"empty_payload": 1}
    row = rows[0]
    labels = _split_csv_text(row.get("_lvb_lbl_14h"))
    titles = _split_csv_text(row.get("_lvb_ttl"))
    series_values = _split_15m_series(row.get("_lvb_vll_14h"))
    if not labels or not titles or not series_values:
        return [], {"empty_series": 1}
    series = {
        title.casefold(): values for title, values in zip(titles, series_values, strict=False)
    }
    points: list[dict[str, Any]] = []
    day_start = _combine_utc(day)
    for index, label in enumerate(labels):
        timestamp = day_start + timedelta(minutes=15 * (index + 1))
        total = _series_value(series, "Gesamtbezug", index) or 0.0
        pv = _series_value(series, "PV-Bezug", index)
        solar = (pv if pv is not None else _series_value(series, "Objektbezug", index)) or 0.0
        raw_grid = _series_value(series, "Netzbezug", index)
        battery = _series_value(series, "Batterie-Bezug", index) or 0.0
        points.append(
            {
                "timestamp": timestamp,
                "label": label,
                "total_kwh": total,
                "solar_kwh": solar,
                "grid_kwh": max(total - solar, 0.0),
                "unsmoothed_total_kwh": total,
                "unsmoothed_solar_kwh": solar,
                "unsmoothed_grid_kwh": max(total - solar, 0.0),
                "raw_grid_kwh": raw_grid,
                "battery_kwh": battery,
            }
        )
    sanitized, _report = _sanitize_interval_points(
        points,
        max_average_kw=max_average_kw,
        smooth_anomalies=smooth_anomalies,
        redistribution_window=redistribution_window,
        smoothing_lookaround_days=smoothing_lookaround_days,
    )
    return sanitized, _report


def _daily_interval_values_from_payload(data: dict[str, Any], day: date) -> list[dict[str, Any]]:
    """Parse one `get_mtr_eb` daily payload into 15-minute interval values."""
    points, _report = _daily_interval_values_and_report_from_payload(data, day)
    return points


def _overview_metrics_from_payload(data: dict[str, Any]) -> dict[str, float]:
    """Extract current-year overview metrics from Astra's overview payload."""
    metrics: dict[str, float] = {}
    for row in data.get("data") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("v01") or "").casefold()
        value = _parse_number(row.get("v02"))
        if value is None:
            continue
        if key == "str_mtr_vbo_vb_strom_gesbez":
            metrics["current_year_total_kwh"] = value
        elif key == "str_mtr_vbo_vb_strom_t1":
            metrics["current_year_raw_grid_kwh"] = value
        elif key in {"str_mtr_vbo_strom_t2", "str_mtr_vbo_vb_strom_pv"}:
            metrics["current_year_solar_kwh"] = value
        elif key == "str_mtr_vbo_vmco_strom_pv":
            metrics["pv_co2_savings_t"] = value
        elif key == "str_mtr_vbo_autarkiegrad":
            metrics["autarky_percent"] = value

    total = metrics.get("current_year_total_kwh")
    solar = metrics.get("current_year_solar_kwh")
    if total is not None and solar is not None:
        metrics["current_year_grid_kwh"] = max(total - solar, 0.0)
    elif metrics.get("current_year_raw_grid_kwh") is not None:
        metrics["current_year_grid_kwh"] = metrics["current_year_raw_grid_kwh"]
    return metrics


def _monthly_metrics_from_payload(data: dict[str, Any], month_index: int) -> dict[str, float]:
    """Extract current-month metrics from Astra's monthly medium payload."""
    metrics: dict[str, float] = {}
    rows = data.get("data") or []
    if not rows or not isinstance(rows[0], dict):
        return metrics
    row = rows[0]
    titles = _split_csv_text(row.get("_hvb_ttl") or row.get("_vb_ttl"))
    values = _split_15m_series(row.get("_hvb_vll") or row.get("_vb_vll"))
    if not titles or not values:
        return metrics
    series = {
        title.casefold(): numbers for title, numbers in zip(titles, values, strict=False)
    }

    def value(name: str) -> float | None:
        numbers = series.get(name.casefold())
        if not numbers or month_index >= len(numbers):
            return None
        return numbers[month_index]

    total = value("Gesamtbezug")
    raw_grid = value("Netzbezug")
    solar = value("Objektbezug")
    pv = value("PV-Bezug")
    if solar is None or (solar == 0 and pv is not None):
        solar = pv
    if total is not None:
        metrics["current_month_total_kwh"] = total
    if raw_grid is not None:
        metrics["current_month_raw_grid_kwh"] = raw_grid
    if solar is not None:
        metrics["current_month_solar_kwh"] = solar
    if total is not None and solar is not None:
        metrics["current_month_grid_kwh"] = max(total - solar, 0.0)
    elif raw_grid is not None:
        metrics["current_month_grid_kwh"] = raw_grid
    return metrics


class AstraClient:
    """Small async client for Astra energy data."""

    def __init__(
        self,
        session: ClientSession,
        *,
        username: str,
        password: str,
        base_url: str,
        grid_price_net: float = DEFAULT_GRID_PRICE_NET,
        solar_price_net: float = DEFAULT_SOLAR_PRICE_NET,
        tax_rate: float = DEFAULT_TAX_RATE,
        max_interval_average_kw: float = DEFAULT_MAX_INTERVAL_AVERAGE_KW,
        smooth_interval_anomalies: bool = DEFAULT_SMOOTH_INTERVAL_ANOMALIES,
        anomaly_redistribution_window: int = DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW,
        smoothing_lookaround_days: int = DEFAULT_SMOOTHING_LOOKAROUND_DAYS,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._authenticated = False
        self._sid = _session_id(username, password)
        self._location_id = "-1"
        self._year = str(datetime.now().year)
        self._month = "-1"
        self._date = "-1"
        self._medium = "1"
        self._language = "de"
        self._last_login_payload: dict[str, Any] = {}
        self._grid_price_net = float(grid_price_net)
        self._solar_price_net = float(solar_price_net)
        self._tax_rate = float(tax_rate)
        self._max_interval_average_kw = float(max_interval_average_kw)
        self._smooth_interval_anomalies = bool(smooth_interval_anomalies)
        self._anomaly_redistribution_window = int(anomaly_redistribution_window)
        self._smoothing_lookaround_days = int(smoothing_lookaround_days)

    async def _post_action(self, action: str, **params: str) -> str:  # pragma: no cover
        """POST one Android API action and verify Astra's MD5 response suffix."""
        timestamp = await self._post_raw(
            {
                "s_action": "get_ts",
                "s_ts": "",
                "s_cs": _checksum("get_ts", ""),
            }
        )
        payload = {
            "s_action": action,
            "s_ts": timestamp,
            "s_cs": _checksum(action, timestamp),
            **params,
        }
        return await self._post_raw(payload)

    async def _post_raw(self, payload: dict[str, str]) -> str:  # pragma: no cover
        """POST form data and return the checksum-verified body payload."""
        payload = {**payload, "s_dv": "1"}
        try:
            async with self._session.post(
                self._base_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    raise AstraApiError(f"Astra HTTP {response.status}")
        except AstraApiError:
            raise
        except Exception as err:  # noqa: BLE001
            raise AstraApiError(f"Astra request failed: {type(err).__name__}: {err}") from err
        if len(text) < 32:
            raise AstraProtocolError("Astra response is too short")
        body = text[:-32]
        checksum = text[-32:]
        if _md5(body) != checksum:
            raise AstraProtocolError("Astra response checksum mismatch")
        return body

    async def async_login(self) -> None:  # pragma: no cover
        """Authenticate through the Android JSON endpoint."""
        payload = await self._post_action(
            "auth_login",
            s_sid=self._sid,
            s_immo=self._location_id,
            s_year=self._year,
            s_med=self._medium,
            s_lang=self._language,
            s_mnt=self._month,
            s_datum=self._date,
        )
        try:
            data = json.loads(payload)
        except ValueError as err:
            raise AstraProtocolError("Astra login response is not JSON") from err
        if str(data.get("auth", "0")) != "1":
            raise AstraAuthError("Astra authentication failed")
        self._last_login_payload = data
        self._location_id = str(data.get("immo_sel") or self._location_id)
        self._authenticated = True

    async def async_get_account_info(self) -> AstraAccountInfo:  # pragma: no cover
        """Authenticate and return basic account information."""
        if not self._authenticated:
            await self.async_login()
        locations = self._last_login_payload.get("standort_list") or []
        selected_location_name = None
        for location in locations:
            if str(location.get("id")) == self._location_id:
                selected_location_name = str(location.get("name") or "")
                break
        return AstraAccountInfo(
            username=str(self._last_login_payload.get("user") or self._username),
            company_id=str(self._last_login_payload.get("comp_id") or "") or None,
            company_name=str(self._last_login_payload.get("comp_name") or "") or None,
            selected_location_id=self._location_id,
            selected_location_name=selected_location_name,
            is_tenant=str(self._last_login_payload.get("is_mieter") or "0") == "1",
        )

    async def _get_json(self, action: str, **overrides: str) -> dict[str, Any]:  # pragma: no cover
        """Fetch one authenticated JSON endpoint."""
        if not self._authenticated:
            await self.async_login()
        started = perf_counter()
        params = {
            "s_sid": self._sid,
            "s_immo": self._location_id,
            "s_year": self._year,
            "s_mnt": self._month,
            "s_datum": self._date,
            "s_med": self._medium,
            "s_lang": self._language,
        }
        params.update(overrides)
        payload = await self._post_action(
            action,
            **params,
        )
        try:
            data = json.loads(payload)
        except ValueError as err:
            raise AstraProtocolError(f"Astra {action} response is not JSON") from err
        if str(data.get("auth", "0")) != "1":
            self._authenticated = False
            raise AstraAuthError("Astra session expired")
        rows = data.get("data")
        row_count = len(rows) if isinstance(rows, list) else None
        _LOGGER.debug(
            "Astra API action=%s year=%s month=%s date=%s medium=%s rows=%s elapsed=%.3fs",
            action,
            params.get("s_year"),
            params.get("s_mnt"),
            params.get("s_datum"),
            params.get("s_med"),
            row_count,
            perf_counter() - started,
        )
        return data

    async def async_get_meters(self) -> list[AstraMeterReading]:  # pragma: no cover
        """Return latest readings for all configured meters."""
        if not self._authenticated:
            await self.async_login()
        readings = await self._read_latest_meter_stands()
        if readings:
            balance_values = await self._read_energy_balance_values()
            overview_values = await self._read_overview_metrics()
            monthly_values = await self._read_monthly_metrics()
            if balance_values:
                first = readings[0]
                readings[0] = replace(
                    first,
                    grid_kwh_total=balance_values.get("grid_kwh_total") or first.grid_kwh_total,
                    solar_kwh_total=balance_values.get("solar_kwh_total") or first.solar_kwh_total,
                    total_kwh=balance_values.get("total_kwh") or first.total_kwh,
                    unsmoothed_grid_kwh_total=(
                        balance_values.get("grid_kwh_total") or first.unsmoothed_grid_kwh_total
                    ),
                    unsmoothed_solar_kwh_total=(
                        balance_values.get("solar_kwh_total") or first.unsmoothed_solar_kwh_total
                    ),
                    unsmoothed_total_kwh=(
                        balance_values.get("total_kwh") or first.unsmoothed_total_kwh
                    ),
                    raw={
                        **(first.raw or {}),
                        "energy_balance": {
                            key: value for key, value in balance_values.items() if value is not None
                        },
                    },
                )
            readings[0] = self._reading_with_metrics(
                readings[0],
                overview_values=overview_values,
                monthly_values=monthly_values,
            )
            return readings
        return [
            self._reading_with_metrics(reading)
            for reading in await self._read_overview_values()
        ]

    def _reading_with_metrics(
        self,
        reading: AstraMeterReading,
        *,
        overview_values: dict[str, float] | None = None,
        monthly_values: dict[str, float] | None = None,
    ) -> AstraMeterReading:
        """Attach tariff, current-year, and current-month metrics to a reading."""
        overview_values = overview_values or {}
        monthly_values = monthly_values or {}
        grid_price_gross = _round_or_none(self._grid_price_net * (1 + self._tax_rate))
        solar_price_gross = _round_or_none(self._solar_price_net * (1 + self._tax_rate))
        current_month_grid = monthly_values.get("current_month_grid_kwh")
        current_month_solar = monthly_values.get("current_month_solar_kwh")
        current_year_grid = overview_values.get("current_year_grid_kwh")
        current_year_solar = overview_values.get("current_year_solar_kwh")
        return replace(
            reading,
            grid_price_net_eur_per_kwh=self._grid_price_net,
            grid_price_gross_eur_per_kwh=grid_price_gross,
            solar_price_net_eur_per_kwh=self._solar_price_net,
            solar_price_gross_eur_per_kwh=solar_price_gross,
            tax_rate=self._tax_rate,
            current_month_grid_kwh=current_month_grid,
            current_month_solar_kwh=current_month_solar,
            current_month_total_kwh=monthly_values.get("current_month_total_kwh"),
            current_month_raw_grid_kwh=monthly_values.get("current_month_raw_grid_kwh"),
            current_month_grid_cost_gross_eur=_cost_gross(
                current_month_grid, grid_price_gross
            ),
            current_month_solar_cost_gross_eur=_cost_gross(
                current_month_solar, solar_price_gross
            ),
            current_month_total_cost_gross_eur=_round_or_none(
                (_cost_gross(current_month_grid, grid_price_gross) or 0.0)
                + (_cost_gross(current_month_solar, solar_price_gross) or 0.0),
                4,
            )
            if current_month_grid is not None or current_month_solar is not None
            else None,
            current_year_grid_kwh=current_year_grid,
            current_year_solar_kwh=current_year_solar,
            current_year_total_kwh=overview_values.get("current_year_total_kwh"),
            current_year_raw_grid_kwh=overview_values.get("current_year_raw_grid_kwh"),
            current_year_grid_cost_gross_eur=_cost_gross(current_year_grid, grid_price_gross),
            current_year_solar_cost_gross_eur=_cost_gross(
                current_year_solar, solar_price_gross
            ),
            current_year_total_cost_gross_eur=_round_or_none(
                (_cost_gross(current_year_grid, grid_price_gross) or 0.0)
                + (_cost_gross(current_year_solar, solar_price_gross) or 0.0),
                4,
            )
            if current_year_grid is not None or current_year_solar is not None
            else None,
            autarky_percent=overview_values.get("autarky_percent"),
            pv_co2_savings_t=overview_values.get("pv_co2_savings_t"),
            raw={
                **(reading.raw or {}),
                "overview": overview_values,
                "monthly": monthly_values,
                "tariff": {
                    "grid_price_net_eur_per_kwh": self._grid_price_net,
                    "solar_price_net_eur_per_kwh": self._solar_price_net,
                    "tax_rate": self._tax_rate,
                    "source": "configured_observed_astra_tariff",
                },
            },
        )

    async def async_get_history(  # pragma: no cover
        self,
        meter_id: str,
        start: datetime,
        end: datetime,
    ) -> list[AstraMeterReading]:
        """Return historical interval or cumulative readings for one meter."""
        if not self._authenticated:
            await self.async_login()
        readings = await self.async_get_historical_meter_stands(start, end)
        if meter_id:
            readings = [reading for reading in readings if reading.meter_id == meter_id]
        return readings

    async def async_get_historical_meter_stands(  # pragma: no cover
        self,
        start: datetime,
        end: datetime,
    ) -> list[AstraMeterReading]:
        """Fetch historical meter stands for the month range around start/end."""
        if not self._authenticated:
            await self.async_login()
        start_date = start.date()
        end_date = end.date()
        readings_by_key: dict[tuple[str, datetime | None, float | None], AstraMeterReading] = {}
        for year, month in _iter_months(start_date, end_date):
            data = await self._get_json(
                "get_mtr_lzs",
                s_year=str(year),
                s_mnt=str(month),
                s_datum="-1",
            )
            for reading in self._meter_stands_from_payload(data):
                if reading.timestamp and not (start <= reading.timestamp <= end):
                    continue
                readings_by_key[
                    (reading.meter_id, reading.timestamp, reading.imported_kwh_total)
                ] = reading
        return sorted(
            readings_by_key.values(),
            key=lambda reading: (reading.timestamp or datetime.min, reading.meter_id),
        )

    async def async_get_historical_interval_meter_stands(  # pragma: no cover
        self,
        start: datetime,
        end: datetime,
        *,
        payload_cache: dict[str, dict[str, Any]] | None = None,
        cache_before: datetime | None = None,
        max_average_kw: float | None = None,
        smooth_anomalies: bool | None = None,
        redistribution_window: int | None = None,
        smoothing_lookaround_days: int | None = None,
    ) -> list[AstraMeterReading]:
        """Fetch 15-minute energy balance intervals as cumulative readings."""
        if not self._authenticated:
            await self.async_login()
        max_average_kw = (
            self._max_interval_average_kw if max_average_kw is None else max_average_kw
        )
        smooth_anomalies = (
            self._smooth_interval_anomalies if smooth_anomalies is None else smooth_anomalies
        )
        redistribution_window = (
            self._anomaly_redistribution_window
            if redistribution_window is None
            else redistribution_window
        )
        smoothing_lookaround_days = (
            self._smoothing_lookaround_days
            if smoothing_lookaround_days is None
            else smoothing_lookaround_days
        )

        latest_readings = await self._read_latest_meter_stands()
        template = latest_readings[0] if latest_readings else None
        if template is None:
            monthly_readings = await self.async_get_historical_meter_stands(start, end)
            template = monthly_readings[-1] if monthly_readings else None

        days = _iter_days(start.date(), end.date())
        semaphore = asyncio.Semaphore(DAILY_INTERVAL_CONCURRENCY)
        cache_before_date = cache_before.date() if cache_before else None
        payload_cache = payload_cache if payload_cache is not None else {}
        cache_hits = 0
        fetched = 0

        async def fetch_day(day: date) -> tuple[date, dict[str, Any]]:
            nonlocal cache_hits, fetched
            cache_key = day.isoformat()
            if cache_before_date is not None and day < cache_before_date and cache_key in payload_cache:
                cache_hits += 1
                return day, payload_cache[cache_key]
            async with semaphore:
                data = await self._get_json(
                    "get_mtr_eb",
                    s_year=str(day.year),
                    s_mnt=str(day.month),
                    s_datum=day.isoformat(),
                )
                fetched += 1
                payload_cache[cache_key] = data
                return day, data

        payloads = await asyncio.gather(*(fetch_day(day) for day in days))
        points = []
        invalid_hours: set[datetime] = set()
        anomaly_report: dict[str, int] = {}
        for day, data in sorted(payloads, key=lambda item: item[0]):
            day_points, day_report = _daily_interval_values_and_report_from_payload(
                data,
                day,
                max_average_kw=max_average_kw,
                smooth_anomalies=smooth_anomalies,
                redistribution_window=redistribution_window,
                smoothing_lookaround_days=smoothing_lookaround_days,
            )
            for key, value in day_report.items():
                anomaly_report[key] = anomaly_report.get(key, 0) + value
            for point in day_points:
                if not (start <= point["timestamp"] <= end):
                    continue
                if not point.get("valid", True):
                    invalid_hours.add(_interval_hour_start(point["timestamp"]))
                    continue
                points.append(point)
        if invalid_hours:
            points = [
                point
                for point in points
                if _interval_hour_start(point["timestamp"]) not in invalid_hours
            ]
            anomaly_report["missing_hour_buckets"] = len(invalid_hours)
        if anomaly_report:
            _LOGGER.warning(
                "Astra sanitized historical interval payloads: %s",
                anomaly_report,
            )
        _LOGGER.info(
            "Astra historical interval fetch window %s to %s: %s days fetched, %s days cached",
            start.date().isoformat(),
            end.date().isoformat(),
            fetched,
            cache_hits,
        )

        end_total = _total_or_zero(template.total_kwh if template else None)
        end_solar = _total_or_zero(template.solar_kwh_total if template else None)
        end_grid = _total_or_zero(template.grid_kwh_total if template else None)
        if end_grid == 0.0 and end_total > 0.0:
            end_grid = max(end_total - end_solar, 0.0)
        totals = {
            "grid": max(end_grid - sum(point["grid_kwh"] for point in points), 0.0),
            "solar": max(end_solar - sum(point["solar_kwh"] for point in points), 0.0),
            "total": max(end_total - sum(point["total_kwh"] for point in points), 0.0),
            "unsmoothed_grid": max(
                end_grid - sum(point["unsmoothed_grid_kwh"] for point in points), 0.0
            ),
            "unsmoothed_solar": max(
                end_solar - sum(point["unsmoothed_solar_kwh"] for point in points), 0.0
            ),
            "unsmoothed_total": max(
                end_total - sum(point["unsmoothed_total_kwh"] for point in points), 0.0
            ),
        }
        readings: list[AstraMeterReading] = []
        for point in sorted(points, key=lambda item: item["timestamp"]):
            totals["total"] += point["total_kwh"]
            totals["solar"] += point["solar_kwh"]
            totals["grid"] += point["grid_kwh"]
            totals["unsmoothed_total"] += point["unsmoothed_total_kwh"]
            totals["unsmoothed_solar"] += point["unsmoothed_solar_kwh"]
            totals["unsmoothed_grid"] += point["unsmoothed_grid_kwh"]
            readings.append(
                _reading_from_interval_point(
                    point,
                    totals,
                    template=template,
                )
            )
        return readings

    async def _read_latest_meter_stands(self) -> list[AstraMeterReading]:  # pragma: no cover
        """Read latest meter stands from `get_mtr_lzs`."""
        data = await self._get_json("get_mtr_lzs")
        return self._meter_stands_from_payload(data)

    def _meter_stands_from_payload(self, data: dict[str, Any]) -> list[AstraMeterReading]:
        """Parse `get_mtr_lzs` JSON into normalized meter readings."""
        channel_rows: list[dict[str, Any]] = []
        for index, row in enumerate(data.get("data") or []):
            if not isinstance(row, dict):
                continue
            meter_name = str(row.get("v01") or f"Meter {index + 1}")
            total = _parse_number(row.get("v02"))
            unit = str(row.get("v03") or "").lower()
            if total is None or "kwh" not in unit:
                continue
            timestamp = _parse_datetime(row.get("v05"))
            medium = str(row.get("v06") or "")
            account = str(row.get("v07") or "")
            legacy_meter_id = _derived_meter_id(meter_name, medium, account)
            raw_meter_id = _raw_meter_id_from_row(row)
            channel_rows.append(
                {
                    "account": account,
                    "interval_consumption": _parse_number(row.get("v04")),
                    "legacy_meter_id": legacy_meter_id,
                    "medium": medium,
                    "meter_name": meter_name,
                    "raw_meter_id": raw_meter_id,
                    "row": _raw_payload_without_ids(row),
                    "timestamp": timestamp,
                    "total": total,
                    "unit": row.get("v03"),
                    "kind": _meter_channel_kind(meter_name, medium, account),
                }
            )
        if len(channel_rows) <= 1:
            return [_reading_from_channel(row) for row in channel_rows]
        return [_combined_reading_from_channels(channel_rows)]

    async def _read_energy_balance_values(self) -> dict[str, float | None]:  # pragma: no cover
        """Read optional grid/solar energy channels from Astra's energy balance card."""
        try:
            data = await self._get_json("get_mtr_eb")
        except AstraApiError:
            return {}
        return _energy_balance_values_from_payload(data)

    async def _read_overview_metrics(self) -> dict[str, float]:  # pragma: no cover
        """Read current-year overview metrics from Astra."""
        try:
            data = await self._get_json("get_mtr_vb_overview")
        except AstraApiError:
            return {}
        return _overview_metrics_from_payload(data)

    async def _read_monthly_metrics(self) -> dict[str, float]:  # pragma: no cover
        """Read current-month medium metrics from Astra."""
        today = datetime.now(UTC).date()
        try:
            data = await self._get_json(
                "get_mtr_vbmed",
                s_year=str(today.year),
                s_mnt="-1",
                s_datum="-1",
            )
        except AstraApiError:
            return {}
        return _monthly_metrics_from_payload(data, today.month - 1)

    async def _read_overview_values(self) -> list[AstraMeterReading]:  # pragma: no cover
        """Fallback to tenant overview values when no meter stand is exposed."""
        data = await self._get_json("get_mtr_vb_overview")
        readings: list[AstraMeterReading] = []
        for index, row in enumerate(data.get("data") or []):
            if not isinstance(row, dict):
                continue
            label = str(row.get("v01") or f"Overview {index + 1}")
            unit = str(row.get("v03") or "").lower()
            value = _parse_number(row.get("v02"))
            if value is None or "kwh" not in unit:
                continue
            meter_id = _md5(f"overview|{label}")[:16]
            readings.append(
                AstraMeterReading(
                    meter_id=meter_id,
                    meter_name=label,
                    timestamp=None,
                    power_w=None,
                    imported_kwh_total=value,
                    grid_kwh_total=value,
                    total_kwh=value,
                    unsmoothed_grid_kwh_total=value,
                    unsmoothed_total_kwh=value,
                    legacy_meter_id=meter_id,
                    raw={"action": "get_mtr_vb_overview", "unit": row.get("v03")},
                )
            )
        return readings


def _energy_balance_values_from_payload(data: dict[str, Any]) -> dict[str, float | None]:
    """Extract cumulative-looking grid and PV values from an energy balance payload."""
    values: dict[str, float | None] = {}

    def visit(value: Any, label_hint: str = "") -> None:
        if isinstance(value, dict):
            label = str(
                value.get("label")
                or value.get("name")
                or value.get("title")
                or value.get("v01")
                or label_hint
            )
            unit = str(value.get("unit") or value.get("v03") or value.get("eh") or "").lower()
            amount = _parse_number(
                value.get("value")
                or value.get("val")
                or value.get("v02")
                or value.get("_vb_vll")
                or value.get("_lvb_vll")
                or value.get("_ez_vll")
            )
            if amount is not None and ("kwh" in unit or "kwh" in label.lower()):
                _assign_energy_balance_value(values, label, amount)
            for key, item in value.items():
                if key in {"value", "val", "v02"}:
                    continue
                visit(item, f"{label} {key}".strip())
        elif isinstance(value, list):
            for item in value:
                visit(item, label_hint)

    visit(data)
    total = values.get("total_kwh")
    solar = values.get("solar_kwh_total")
    if total is not None and solar is not None:
        values["grid_kwh_total"] = max(total - solar, 0.0)
    return values


def _assign_energy_balance_value(
    values: dict[str, float | None], label: str, amount: float
) -> None:
    """Assign one energy-balance value from its label."""
    normalized = label.casefold().replace("-", " ").replace("_", " ")
    if "netzbezug" in normalized or "grid" in normalized:
        values["grid_kwh_total"] = amount
    elif "pv bezug" in normalized or "solar" in normalized or "photovoltaik" in normalized:
        values["solar_kwh_total"] = amount
    elif "gesamtbezug" in normalized or "total" in normalized:
        values["total_kwh"] = amount


def _latest_reading_by_month(
    readings: list[AstraMeterReading],
) -> dict[date, AstraMeterReading]:
    """Return the latest cumulative reading for each reading month."""
    result: dict[date, AstraMeterReading] = {}
    for reading in readings:
        if reading.timestamp is None:
            continue
        key = _first_day_of_month(reading.timestamp.date())
        current = result.get(key)
        if current is None or (
            current.timestamp is not None and reading.timestamp > current.timestamp
        ):
            result[key] = reading
    return result


def _reading_from_interval_point(
    point: dict[str, Any],
    totals: dict[str, float],
    *,
    template: AstraMeterReading | None,
) -> AstraMeterReading:
    """Build one cumulative reading from a 15-minute interval point."""
    meter_id = template.meter_id if template else "astra_meter"
    meter_name = template.meter_name if template else "Astra Energy Meter"
    raw_meter_id = template.raw_meter_id if template else None
    legacy_meter_id = template.legacy_meter_id if template else meter_id
    return AstraMeterReading(
        meter_id=meter_id,
        meter_name=meter_name,
        timestamp=point["timestamp"],
        power_w=point["total_kwh"] * 4000.0,
        imported_kwh_total=totals["grid"],
        grid_kwh_total=totals["grid"],
        solar_kwh_total=totals["solar"],
        total_kwh=totals["total"],
        unsmoothed_grid_kwh_total=totals.get("unsmoothed_grid", totals["grid"]),
        unsmoothed_solar_kwh_total=totals.get("unsmoothed_solar", totals["solar"]),
        unsmoothed_total_kwh=totals.get("unsmoothed_total", totals["total"]),
        raw_meter_id=raw_meter_id,
        legacy_meter_id=legacy_meter_id,
        raw={
            "action": "get_mtr_eb",
            "interval_label": point.get("label"),
            "interval_total_kwh": point["total_kwh"],
            "interval_grid_kwh": point["grid_kwh"],
            "interval_solar_kwh": point["solar_kwh"],
            "unsmoothed_interval_total_kwh": point.get("unsmoothed_total_kwh"),
            "unsmoothed_interval_grid_kwh": point.get("unsmoothed_grid_kwh"),
            "unsmoothed_interval_solar_kwh": point.get("unsmoothed_solar_kwh"),
            "raw_grid_kwh": point.get("raw_grid_kwh"),
            "grid_source": "derived_total_minus_solar",
        },
    )
