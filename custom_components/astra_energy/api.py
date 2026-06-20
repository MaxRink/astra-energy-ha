"""Astra API client."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from hashlib import md5
import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp import ClientSession


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
    exported_kwh_total: float | None = None
    cost_total: float | None = None
    currency: str | None = None
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
            return datetime.strptime(text, fmt)
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
    grid_total = grid_channel["total"] if grid_channel else total_channel["total"]
    solar_total = solar_channel["total"] if solar_channel else None
    return AstraMeterReading(
        meter_id=meter_id,
        meter_name=total_channel["meter_name"],
        timestamp=max(timestamps) if timestamps else None,
        power_w=None,
        imported_kwh_total=grid_total,
        grid_kwh_total=grid_total,
        solar_kwh_total=solar_total,
        total_kwh=total_channel["total"],
        raw_meter_id=raw_meter_id,
        legacy_meter_id=legacy_meter_id,
        raw={
            "action": "get_mtr_lzs",
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


def _first_channel(
    channels: list[dict[str, Any]], kind: str
) -> dict[str, Any] | None:
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


class AstraClient:
    """Small async client for Astra energy data."""

    def __init__(
        self,
        session: ClientSession,
        *,
        username: str,
        password: str,
        base_url: str,
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

    async def _post_action(self, action: str, **params: str) -> str:
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

    async def _post_raw(self, payload: dict[str, str]) -> str:
        """POST form data and return the checksum-verified body payload."""
        payload = {**payload, "s_dv": "1"}
        async with self._session.post(
            self._base_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise AstraApiError(f"Astra HTTP {response.status}")
        if len(text) < 32:
            raise AstraProtocolError("Astra response is too short")
        body = text[:-32]
        checksum = text[-32:]
        if _md5(body) != checksum:
            raise AstraProtocolError("Astra response checksum mismatch")
        return body

    async def async_login(self) -> None:
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

    async def async_get_account_info(self) -> AstraAccountInfo:
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

    async def _get_json(self, action: str, **overrides: str) -> dict[str, Any]:
        """Fetch one authenticated JSON endpoint."""
        if not self._authenticated:
            await self.async_login()
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
        return data

    async def async_get_meters(self) -> list[AstraMeterReading]:
        """Return latest readings for all configured meters."""
        if not self._authenticated:
            await self.async_login()
        readings = await self._read_latest_meter_stands()
        if readings:
            balance_values = await self._read_energy_balance_values()
            if balance_values:
                first = readings[0]
                readings[0] = replace(
                    first,
                    grid_kwh_total=balance_values.get("grid_kwh_total")
                    or first.grid_kwh_total,
                    solar_kwh_total=balance_values.get("solar_kwh_total")
                    or first.solar_kwh_total,
                    total_kwh=balance_values.get("total_kwh") or first.total_kwh,
                    raw={
                        **(first.raw or {}),
                        "energy_balance": {
                            key: value
                            for key, value in balance_values.items()
                            if value is not None
                        },
                    },
                )
            return readings
        return await self._read_overview_values()

    async def async_get_history(
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

    async def async_get_historical_meter_stands(
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

    async def _read_latest_meter_stands(self) -> list[AstraMeterReading]:
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

    async def _read_energy_balance_values(self) -> dict[str, float | None]:
        """Read optional grid/solar energy channels from Astra's energy balance card."""
        try:
            data = await self._get_json("get_mtr_eb")
        except AstraApiError:
            return {}
        return _energy_balance_values_from_payload(data)

    async def _read_overview_values(self) -> list[AstraMeterReading]:
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
