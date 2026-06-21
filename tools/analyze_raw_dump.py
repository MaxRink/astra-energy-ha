#!/usr/bin/env python3
"""Analyze ignored Astra raw API captures without Home Assistant."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import types
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
API_PATH = REPO_ROOT / "custom_components" / "astra_energy" / "api.py"

custom_components_pkg = types.ModuleType("custom_components")
custom_components_pkg.__path__ = []
astra_pkg = types.ModuleType("custom_components.astra_energy")
astra_pkg.__path__ = [str(API_PATH.parent)]
sys.modules.setdefault("custom_components", custom_components_pkg)
sys.modules.setdefault("custom_components.astra_energy", astra_pkg)

spec = importlib.util.spec_from_file_location("custom_components.astra_energy.api", API_PATH)
if not spec or not spec.loader:
    raise RuntimeError(f"Could not load Astra API module from {API_PATH}")
astra_api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = astra_api
spec.loader.exec_module(astra_api)

AstraClient = astra_api.AstraClient
_parse_number = astra_api._parse_number

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def main() -> int:
    """Analyze raw dump files."""
    parser = argparse.ArgumentParser()
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--show-ids", action="store_true")
    args = parser.parse_args()

    for path in args.captures:
        analyze_capture(path, show_ids=args.show_ids)
    return 0


def analyze_capture(path: Path, *, show_ids: bool) -> None:
    """Print a compact analysis for one capture."""
    data = json.loads(path.read_text(encoding="utf-8"))
    year = data.get("request_defaults", {}).get("s_year")
    print(f"\n== {path} ({year}) ==")
    print(f"captured_at: {data.get('captured_at')}")

    actions = data.get("actions") or {}
    failed = [
        f"{name}: {result.get('error', {}).get('type')}"
        for name, result in sorted(actions.items())
        if not result.get("ok")
    ]
    print(f"actions: {len(actions)} total, {len(failed)} failed")
    if failed:
        print("failed:", ", ".join(failed))

    latest = _latest_meter_reading(actions)
    if latest:
        meter_id = latest.meter_id if show_ids else _mask_id(latest.meter_id)
        print(f"meter: {meter_id}")
        print(
            "latest cumulative kWh: "
            f"total={_fmt(latest.total_kwh)}, "
            f"grid={_fmt(latest.grid_kwh_total)}, "
            f"solar_object={_fmt(latest.solar_kwh_total)}"
        )

    balance = _energy_balance(actions)
    if balance:
        print("monthly consumption totals:")
        for label in ("Gesamtbezug", "Netzbezug", "Objektbezug"):
            values = balance.get(label)
            if values:
                print(f"  {label}: {_fmt(sum(values))} kWh over {_covered_months(values)} month(s)")
        total = sum(balance.get("Gesamtbezug") or [])
        grid = sum(balance.get("Netzbezug") or [])
        solar = sum(balance.get("Objektbezug") or [])
        if total:
            print(
                f"  split: grid={grid / total * 100:.1f}%, solar_object={solar / total * 100:.1f}%"
            )

    generation = _generation_balance(actions)
    if generation:
        print("monthly PV generation/delivery totals:")
        for label in ("PV-Gesamtlieferung", "PV-Netzlieferung", "PV-Objektlieferung"):
            values = generation.get(label)
            if values:
                print(f"  {label}: {_fmt(sum(values))} kWh over {_covered_months(values)} month(s)")

    overview = _overview(actions)
    if overview:
        autarky = overview.get("str_mtr_vbo_autarkiegrad")
        co2 = overview.get("str_mtr_vbo_vmco_strom_pv")
        if autarky is not None:
            print(f"overview autarky: {_fmt(autarky)}%")
        if co2 is not None:
            print(f"overview PV CO2 saving: {_fmt(co2)} t")


def _latest_meter_reading(actions: dict[str, Any]):
    """Return the normalized latest meter reading."""
    result = actions.get("get_mtr_lzs") or {}
    if not result.get("ok"):
        return None
    client = AstraClient(
        object(),
        username="analysis@example.invalid",
        password="unused",
        base_url="https://example.invalid",
    )
    readings = client._meter_stands_from_payload(result.get("payload") or {})
    return readings[0] if readings else None


def _energy_balance(actions: dict[str, Any]) -> dict[str, list[float]]:
    """Return consumption balance series from get_mtr_eb."""
    result = actions.get("get_mtr_eb") or {}
    if not result.get("ok"):
        return {}
    row = ((result.get("payload") or {}).get("data") or [{}])[0]
    return _series_from_row(row, "_lvb_ttl", "_lvb_vll")


def _generation_balance(actions: dict[str, Any]) -> dict[str, list[float]]:
    """Return PV generation/delivery series from get_mtr_eb."""
    result = actions.get("get_mtr_eb") or {}
    if not result.get("ok"):
        return {}
    row = ((result.get("payload") or {}).get("data") or [{}])[0]
    return _series_from_row(row, "_lez_ttl", "_lez_vll")


def _overview(actions: dict[str, Any]) -> dict[str, float]:
    """Return parsed overview scalar values."""
    result = actions.get("get_mtr_vb_overview") or {}
    if not result.get("ok"):
        return {}
    rows = (result.get("payload") or {}).get("data") or []
    parsed: dict[str, float] = {}
    for row in rows:
        label = str(row.get("v01") or "")
        value = _parse_number(row.get("v02"))
        if label and value is not None:
            parsed[label] = value
    return parsed


def _series_from_row(
    row: dict[str, Any], labels_key: str, values_key: str
) -> dict[str, list[float]]:
    """Parse Astra's semicolon-separated label/value matrices."""
    labels = [label.strip() for label in str(row.get(labels_key) or "").split(",") if label.strip()]
    series = [
        [_parse_number(value) or 0.0 for value in line.split(",")]
        for line in str(row.get(values_key) or "").split(";")
        if line
    ]
    return dict(zip(labels, series, strict=False))


def _covered_months(values: list[float]) -> int:
    """Count non-zero months."""
    return sum(1 for value in values if value)


def _fmt(value: float | None) -> str:
    """Format numeric output."""
    if value is None:
        return "n/a"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _mask_id(value: str) -> str:
    """Mask a meter id for terminal summaries."""
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


if __name__ == "__main__":
    raise SystemExit(main())
