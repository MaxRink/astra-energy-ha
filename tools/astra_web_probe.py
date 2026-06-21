#!/usr/bin/env python3
"""Probe Astra's web report endpoints and export local analysis artifacts."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from html import unescape
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import urllib.request

try:
    from tools.env_loader import getenv
except ModuleNotFoundError:
    from env_loader import getenv


GRAPH_IDS = {
    "total": "-24557",
    "grid": "-26183",
    "solar": "-26184",
}
TITLE_RE = re.compile(
    r'TITLE="[^"]* ist\s+([0-9.,-]+)\s+kWh\s+um\s+'
    r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)
PRICE_RE = re.compile(
    r"(?:preis|tarif|kosten|betrag|eur|€/kwh|ct/kwh|mwst)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Point:
    """One cumulative and interval graph point."""

    timestamp: datetime
    cumulative_kwh: float
    interval_kwh: float

    @property
    def average_kw(self) -> float:
        """Return average kW for a 15-minute interval."""
        return self.interval_kwh * 4


def main() -> int:
    """Fetch web reports and write CSV/SVG artifacts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", default="captures/web-login.jsonl")
    parser.add_argument("--out-dir", default="captures")
    parser.add_argument("--session-id", default=getenv("ASTRA_WEB_SESSION_ID"))
    parser.add_argument("--cookie", default=getenv("ASTRA_WEB_COOKIE"))
    parser.add_argument("--start", default="2026-06-19 00:00:00")
    parser.add_argument("--end", default="2026-06-20 00:00:00")
    parser.add_argument("--width", default="1600")
    parser.add_argument("--height", default="900")
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    capture = Path(args.capture)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session_id = args.session_id or _extract_session_id(capture)
    report_urls = _extract_report_urls(capture) if capture.exists() else []
    date_slug = args.start[:10]

    all_points: dict[str, list[Point]] = {}
    for name, graph_id in GRAPH_IDS.items():
        html_path = out_dir / f"pm-graph-{name}-{date_slug}.html"
        if not args.skip_fetch or not html_path.exists():
            html = _fetch_graph(
                session_id=session_id,
                graph_id=graph_id,
                start=args.start,
                end=args.end,
                width=args.width,
                height=args.height,
                cookie=args.cookie,
            )
            html_path.write_text(html, encoding="latin-1", errors="ignore")
        else:
            html = html_path.read_text(encoding="latin-1", errors="ignore")
        all_points[name] = parse_graph_points(html)

    csv_path = out_dir / f"astra-15min-{date_slug}.csv"
    _write_points_csv(csv_path, all_points)
    _write_svg(
        out_dir / f"astra-15min-cumulative-{date_slug}.svg",
        "Astra 15-minute cumulative meter readings",
        all_points,
        lambda point: point.cumulative_kwh,
        "kWh",
    )
    _write_svg(
        out_dir / f"astra-15min-power-{date_slug}.svg",
        "Astra 15-minute average power",
        all_points,
        lambda point: point.average_kw,
        "kW",
    )

    fetched_reports = []
    for index, url in enumerate(report_urls, 1):
        path = out_dir / f"astra-web-report-{index:02d}.html"
        if not args.skip_fetch or not path.exists():
            try:
                path.write_text(
                    _fetch_url(url, cookie=args.cookie),
                    encoding="latin-1",
                    errors="ignore",
                )
                time.sleep(0.25)
            except Exception as err:  # noqa: BLE001
                fetched_reports.append({"path": str(path), "error": str(err)})
                continue
        fetched_reports.append({"path": str(path), "pricing_hints": _pricing_hints(path)})

    summary = {
        "csv": str(csv_path),
        "graphs": [
            str(out_dir / f"astra-15min-cumulative-{date_slug}.svg"),
            str(out_dir / f"astra-15min-power-{date_slug}.svg"),
        ],
        "points": {name: len(points) for name, points in all_points.items()},
        "reports": fetched_reports,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def parse_graph_points(html: str) -> list[Point]:
    """Parse cumulative and interval values from an Astra graph image map."""
    values_by_ts: dict[datetime, list[float]] = {}
    for raw_value, raw_ts in TITLE_RE.findall(html):
        timestamp = datetime.strptime(raw_ts, "%d.%m.%Y %H:%M:%S")
        values_by_ts.setdefault(timestamp, []).append(_parse_number(raw_value))

    points: list[Point] = []
    for timestamp, values in sorted(values_by_ts.items()):
        positives = [value for value in values if value >= 0]
        if not positives:
            continue
        cumulative = max(positives)
        interval = min(positives)
        points.append(Point(timestamp, cumulative, interval))
    return points


def _fetch_graph(
    *,
    session_id: str,
    graph_id: str,
    start: str,
    end: str,
    width: str,
    height: str,
    cookie: str | None = None,
) -> str:
    start_de = _to_de_datetime(start)
    end_de = _to_de_datetime(end)
    params = {
        "sessionId": session_id,
        "s_vom": start_de,
        "s_bis": end_de,
        "s_tvom": start,
        "s_tbis": end,
        "s_bvom": start,
        "s_bbis": end,
        "id": graph_id,
        "s_prod": "",
        "s_width": width,
        "s_height": height,
    }
    url = "https://astra-cloud.com/astra04/readyxnet/source/pm/pm_graph.php?" + urlencode(params)
    return _fetch_url(url, cookie=cookie)


def _fetch_url(url: str, *, cookie: str | None = None) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 AstraEnergyProbe/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("latin-1", errors="ignore")


def _extract_session_id(path: Path) -> str:
    for line in path.read_text(errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        request = (item.get("params") or {}).get("request") or {}
        url = request.get("url") or ""
        params = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        session_id = params.get("sessionId")
        if session_id:
            return session_id
    raise RuntimeError(f"no web sessionId found in {path}")


def _extract_report_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        request = (item.get("params") or {}).get("request") or {}
        url = request.get("url") or ""
        if not url:
            continue
        if any(endpoint in url for endpoint in ("pm_prbzgww.php", "pm_repeaverbr.php", "pm_repzw.php")):
            urls.append(url)
    return sorted(set(urls))


def _pricing_hints(path: Path) -> list[str]:
    hints = []
    text = path.read_text(encoding="latin-1", errors="ignore")
    for match in PRICE_RE.finditer(text):
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 160)
        hints.append(_clean_html(text[start:end]))
        if len(hints) >= 12:
            break
    return hints


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    text = re.sub(r"(sessionId=)[^&\s]+", r"\1<redacted>", text)
    return text[:260]


def _write_points_csv(path: Path, points_by_name: dict[str, list[Point]]) -> None:
    timestamps = sorted({point.timestamp for points in points_by_name.values() for point in points})
    by_name_ts = {
        name: {point.timestamp: point for point in points}
        for name, points in points_by_name.items()
    }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp",
                "total_cumulative_kwh",
                "total_interval_kwh",
                "total_average_kw",
                "grid_cumulative_kwh",
                "grid_interval_kwh",
                "grid_average_kw",
                "solar_cumulative_kwh",
                "solar_interval_kwh",
                "solar_average_kw",
            ]
        )
        for timestamp in timestamps:
            row = [timestamp.isoformat(sep=" ")]
            for name in ("total", "grid", "solar"):
                point = by_name_ts.get(name, {}).get(timestamp)
                if point is None:
                    row.extend(["", "", ""])
                else:
                    row.extend(
                        [
                            f"{point.cumulative_kwh:.6f}",
                            f"{point.interval_kwh:.6f}",
                            f"{point.average_kw:.6f}",
                        ]
                    )
            writer.writerow(row)


def _write_svg(
    path: Path,
    title: str,
    points_by_name: dict[str, list[Point]],
    value_getter,
    unit: str,
) -> None:
    width, height = 1200, 620
    left, right, top, bottom = 86, 28, 52, 70
    colors = {"total": "#404040", "grid": "#237ec6", "solar": "#b59b00"}
    all_points = [point for points in points_by_name.values() for point in points]
    if not all_points:
        path.write_text(_empty_svg(width, height, title), encoding="utf-8")
        return
    min_ts = min(point.timestamp for point in all_points).timestamp()
    max_ts = max(point.timestamp for point in all_points).timestamp()
    values = [value_getter(point) for point in all_points]
    min_val = min(values)
    max_val = max(values)
    if max_val == min_val:
        max_val += 1
    plot_w = width - left - right
    plot_h = height - top - bottom

    def xy(point: Point) -> tuple[float, float]:
        ts = point.timestamp.timestamp()
        x = left + ((ts - min_ts) / (max_ts - min_ts or 1)) * plot_w
        y = top + (1 - ((value_getter(point) - min_val) / (max_val - min_val))) * plot_h
        return x, y

    lines = []
    legend = []
    for index, (name, points) in enumerate(points_by_name.items()):
        if not points:
            continue
        path_data = " ".join(
            f"{'M' if i == 0 else 'L'} {x:.1f} {y:.1f}"
            for i, point in enumerate(points)
            for x, y in [xy(point)]
        )
        color = colors[name]
        lines.append(f'<path d="{path_data}" fill="none" stroke="{color}" stroke-width="2.2"/>')
        legend.append(
            f'<g transform="translate({left + index * 170}, {height - 28})">'
            f'<rect width="18" height="3" y="-8" fill="{color}"/>'
            f'<text x="26" y="0">{name}</text></g>'
        )

    grid = []
    for i in range(6):
        y = top + (plot_h / 5) * i
        value = max_val - ((max_val - min_val) / 5) * i
        grid.append(
            f'<line x1="{left}" x2="{width-right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ddd"/>'
            f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end">{value:.2f}</text>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="white"/>'
        '<style>text{font-family:Arial,sans-serif;font-size:14px;fill:#222}'
        '.title{font-size:22px;font-weight:700}</style>'
        f'<text class="title" x="{left}" y="32">{title}</text>'
        f'<text x="{left}" y="{height-48}">{all_points[0].timestamp:%Y-%m-%d %H:%M} '
        f'to {all_points[-1].timestamp:%Y-%m-%d %H:%M}</text>'
        f'<text x="{left}" y="{top-16}">{unit}</text>'
        + "".join(grid)
        + f'<line x1="{left}" x2="{width-right}" y1="{height-bottom}" y2="{height-bottom}" stroke="#888"/>'
        + f'<line x1="{left}" x2="{left}" y1="{top}" y2="{height-bottom}" stroke="#888"/>'
        + "".join(lines)
        + "".join(legend)
        + "</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")


def _empty_svg(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<text x="20" y="40">{title}: no data</text></svg>\n'
    )


def _parse_number(value: str) -> float:
    text = value.strip().replace(".", "").replace(",", ".")
    return float(text)


def _to_de_datetime(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")


def _redact_url(url: str) -> str:
    split = urlsplit(url)
    query = [
        (key, "<redacted>" if key == "sessionId" else value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
    ]
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


if __name__ == "__main__":
    raise SystemExit(main())
