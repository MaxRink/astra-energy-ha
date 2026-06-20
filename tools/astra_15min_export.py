#!/usr/bin/env python3
"""Export Astra Android 15-minute energy-balance payloads to CSV and SVG."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path


SERIES_KEY = "_lvb_vll_14h"
LABEL_KEY = "_lvb_lbl_14h"
TITLE_KEY = "_lvb_ttl"


def main() -> int:
    """Read a raw capture and export quarter-hour interval data."""
    parser = argparse.ArgumentParser()
    parser.add_argument("capture")
    parser.add_argument("--date", required=True, help="Date as YYYY-MM-DD.")
    parser.add_argument("--out-dir", default="captures")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    points = _extract_points(Path(args.capture), args.date)
    csv_path = out_dir / f"astra-15min-energy-balance-{args.date}.csv"
    power_svg = out_dir / f"astra-15min-energy-balance-power-{args.date}.svg"
    energy_svg = out_dir / f"astra-15min-energy-balance-energy-{args.date}.svg"
    _write_csv(csv_path, points)
    _write_svg(
        energy_svg,
        f"Astra 15-minute interval energy {args.date}",
        points,
        ("total_kwh", "grid_kwh", "solar_kwh", "battery_kwh"),
        "kWh",
        multiplier=1.0,
    )
    _write_svg(
        power_svg,
        f"Astra 15-minute average power {args.date}",
        points,
        ("total_kwh", "grid_kwh", "solar_kwh", "battery_kwh"),
        "kW",
        multiplier=4.0,
    )
    summary = {
        "csv": str(csv_path),
        "graphs": [str(energy_svg), str(power_svg)],
        "rows": len(points),
        "totals_kwh": {
            key.removesuffix("_kwh"): round(sum(point[key] for point in points), 6)
            for key in ("total_kwh", "grid_kwh", "solar_kwh", "battery_kwh")
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _extract_points(path: Path, date_text: str) -> list[dict[str, float | str]]:
    data = json.loads(path.read_text())
    row = data["actions"]["get_mtr_eb"]["payload"]["data"][0]
    labels = _split_labels(row[LABEL_KEY])
    names = [name.strip() for name in row[TITLE_KEY].split(",")]
    series = {
        name: values
        for name, values in zip(names, _split_series(row[SERIES_KEY]), strict=False)
    }
    start = datetime.strptime(date_text, "%Y-%m-%d")
    points: list[dict[str, float | str]] = []
    for index, label in enumerate(labels):
        timestamp = start + timedelta(minutes=15 * (index + 1))
        if label == "00:00":
            timestamp = start + timedelta(days=1)
        total = _value(series, "Gesamtbezug", index)
        grid = _value(series, "Netzbezug", index)
        solar = _value(series, "PV-Bezug", index) or _value(series, "Objektbezug", index)
        battery = _value(series, "Batterie-Bezug", index)
        points.append(
            {
                "timestamp": timestamp.isoformat(sep=" "),
                "label": label,
                "total_kwh": total,
                "grid_kwh": grid,
                "solar_kwh": solar,
                "battery_kwh": battery,
                "total_average_kw": total * 4,
                "grid_average_kw": grid * 4,
                "solar_average_kw": solar * 4,
                "battery_average_kw": battery * 4,
            }
        )
    return points


def _split_labels(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_series(value: str) -> list[list[float]]:
    series = []
    for part in value.split(";"):
        series.append(
            [
                float(item.strip().replace(",", "."))
                for item in part.split(",")
                if item.strip()
            ]
        )
    return series


def _value(series: dict[str, list[float]], name: str, index: int) -> float:
    values = series.get(name, [])
    if index >= len(values):
        return 0.0
    return values[index]


def _write_csv(path: Path, points: list[dict[str, float | str]]) -> None:
    fieldnames = [
        "timestamp",
        "label",
        "total_kwh",
        "grid_kwh",
        "solar_kwh",
        "battery_kwh",
        "total_average_kw",
        "grid_average_kw",
        "solar_average_kw",
        "battery_average_kw",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    key: f"{value:.9f}" if isinstance(value, float) else value
                    for key, value in point.items()
                }
            )


def _write_svg(
    path: Path,
    title: str,
    points: list[dict[str, float | str]],
    keys: tuple[str, ...],
    unit: str,
    *,
    multiplier: float,
) -> None:
    width, height = 1200, 620
    left, right, top, bottom = 86, 28, 52, 70
    colors = {
        "total_kwh": "#404040",
        "grid_kwh": "#237ec6",
        "solar_kwh": "#b59b00",
        "battery_kwh": "#7a4fb3",
    }
    values = [float(point[key]) * multiplier for point in points for key in keys]
    min_val, max_val = min(values), max(values)
    if min_val == max_val:
        max_val += 1
    plot_w = width - left - right
    plot_h = height - top - bottom

    def xy(index: int, value: float) -> tuple[float, float]:
        x = left + (index / max(1, len(points) - 1)) * plot_w
        y = top + (1 - ((value - min_val) / (max_val - min_val))) * plot_h
        return x, y

    grid = []
    for i in range(6):
        y = top + (plot_h / 5) * i
        value = max_val - ((max_val - min_val) / 5) * i
        grid.append(
            f'<line x1="{left}" x2="{width-right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ddd"/>'
            f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end">{value:.2f}</text>'
        )
    paths = []
    legends = []
    for key_index, key in enumerate(keys):
        path_data = " ".join(
            f"{'M' if index == 0 else 'L'} {x:.1f} {y:.1f}"
            for index, point in enumerate(points)
            for x, y in [xy(index, float(point[key]) * multiplier)]
        )
        color = colors[key]
        label = key.removesuffix("_kwh")
        paths.append(f'<path d="{path_data}" fill="none" stroke="{color}" stroke-width="2.2"/>')
        legends.append(
            f'<g transform="translate({left + key_index * 170}, {height - 28})">'
            f'<rect width="18" height="3" y="-8" fill="{color}"/>'
            f'<text x="26" y="0">{label}</text></g>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="white"/>'
        '<style>text{font-family:Arial,sans-serif;font-size:14px;fill:#222}'
        '.title{font-size:22px;font-weight:700}</style>'
        f'<text class="title" x="{left}" y="32">{title}</text>'
        f'<text x="{left}" y="{height-48}">{points[0]["timestamp"]} to {points[-1]["timestamp"]}</text>'
        f'<text x="{left}" y="{top-16}">{unit}</text>'
        + "".join(grid)
        + f'<line x1="{left}" x2="{width-right}" y1="{height-bottom}" y2="{height-bottom}" stroke="#888"/>'
        + f'<line x1="{left}" x2="{left}" y1="{top}" y2="{height-bottom}" stroke="#888"/>'
        + "".join(paths)
        + "".join(legends)
        + "</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
