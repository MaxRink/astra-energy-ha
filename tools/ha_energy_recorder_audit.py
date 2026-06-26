#!/usr/bin/env python3
"""Audit Home Assistant Energy dashboard recorder statistics.

This intentionally lives outside the integration runtime. It is a support tool
for diagnosing recorder gaps/spikes in a Home Assistant SQLite database.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class StatisticRow:
    """One long-term statistics row."""

    statistic_id: str
    metadata_id: int
    start_ts: float
    state: float
    sum: float


@dataclass(frozen=True)
class StatisticGap:
    """A gap between two adjacent long-term statistics rows."""

    statistic_id: str
    metadata_id: int
    previous_ts: float
    next_ts: float
    previous_state: float
    next_state: float
    previous_sum: float
    next_sum: float

    @property
    def missing_hours(self) -> int:
        """Return how many hourly rows are missing inside the gap."""
        return int((self.next_ts - self.previous_ts) // 3600) - 1

    @property
    def delta_sum(self) -> float:
        """Return the accumulated sum delta across the gap."""
        return self.next_sum - self.previous_sum

    @property
    def is_monotonic(self) -> bool:
        """Return whether the surrounding rows can be safely interpolated."""
        return self.next_state >= self.previous_state and self.next_sum >= self.previous_sum


@dataclass(frozen=True)
class StatisticDelta:
    """A suspicious adjacent-row delta."""

    statistic_id: str
    previous_ts: float
    next_ts: float
    delta_sum: float
    delta_state: float


def statistic_ids_from_energy_prefs(path: Path) -> list[str]:
    """Read individual-device consumption statistic IDs from an Energy prefs JSON dump."""
    data = json.loads(path.read_text(encoding="utf-8"))
    result: list[str] = []
    for item in data.get("device_consumption", []):
        statistic_id = item.get("stat_consumption")
        if statistic_id and statistic_id not in result:
            result.append(statistic_id)
    return result


def find_statistic_gaps(
    conn: sqlite3.Connection,
    statistic_ids: Sequence[str],
    *,
    start_ts: float | None = None,
    end_ts: float | None = None,
    max_gap_hours: int = 12,
) -> list[StatisticGap]:
    """Find bounded monotonic gaps in long-term statistics."""
    rows = _load_rows(conn, statistic_ids, start_ts=start_ts, end_ts=end_ts)
    gaps: list[StatisticGap] = []
    for previous, current in _pairs(rows):
        if previous.statistic_id != current.statistic_id:
            continue
        gap_hours = int((current.start_ts - previous.start_ts) // 3600)
        if gap_hours <= 1 or gap_hours > max_gap_hours:
            continue
        gap = StatisticGap(
            statistic_id=current.statistic_id,
            metadata_id=current.metadata_id,
            previous_ts=previous.start_ts,
            next_ts=current.start_ts,
            previous_state=previous.state,
            next_state=current.state,
            previous_sum=previous.sum,
            next_sum=current.sum,
        )
        if gap.is_monotonic:
            gaps.append(gap)
    return gaps


def find_suspicious_deltas(
    conn: sqlite3.Connection,
    statistic_ids: Sequence[str],
    *,
    start_ts: float | None = None,
    end_ts: float | None = None,
    max_delta_kwh: float = 2.0,
) -> list[StatisticDelta]:
    """Find negative or unexpectedly large deltas in long-term statistics."""
    rows = _load_rows(conn, statistic_ids, start_ts=start_ts, end_ts=end_ts)
    deltas: list[StatisticDelta] = []
    for previous, current in _pairs(rows):
        if previous.statistic_id != current.statistic_id:
            continue
        delta_sum = current.sum - previous.sum
        delta_state = current.state - previous.state
        if delta_sum < -0.001 or delta_state < -0.001 or abs(delta_sum) > max_delta_kwh:
            deltas.append(
                StatisticDelta(
                    statistic_id=current.statistic_id,
                    previous_ts=previous.start_ts,
                    next_ts=current.start_ts,
                    delta_sum=delta_sum,
                    delta_state=delta_state,
                )
            )
    return deltas


def repair_statistic_gaps(conn: sqlite3.Connection, gaps: Sequence[StatisticGap]) -> int:
    """Insert linearly interpolated hourly rows for repairable gaps."""
    inserted = 0
    for gap in gaps:
        total_hours = int((gap.next_ts - gap.previous_ts) // 3600)
        for hour in range(1, total_hours):
            start_ts = gap.previous_ts + hour * 3600
            ratio = hour / total_hours
            state = gap.previous_state + (gap.next_state - gap.previous_state) * ratio
            stat_sum = gap.previous_sum + (gap.next_sum - gap.previous_sum) * ratio
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO statistics(created_ts, metadata_id, start_ts, state, sum)
                VALUES (unixepoch('now'), ?, ?, ?, ?)
                """,
                (gap.metadata_id, start_ts, state, stat_sum),
            )
            inserted += cursor.rowcount
    return inserted


def _load_rows(
    conn: sqlite3.Connection,
    statistic_ids: Sequence[str],
    *,
    start_ts: float | None,
    end_ts: float | None,
) -> list[StatisticRow]:
    if not statistic_ids:
        return []
    placeholders = ",".join("?" for _ in statistic_ids)
    params: list[object] = list(statistic_ids)
    conditions = [f"m.statistic_id IN ({placeholders})"]
    if start_ts is not None:
        conditions.append("s.start_ts >= ?")
        params.append(start_ts)
    if end_ts is not None:
        conditions.append("s.start_ts <= ?")
        params.append(end_ts)
    sql = f"""
        SELECT m.statistic_id, m.id, s.start_ts, s.state, s.sum
        FROM statistics s
        JOIN statistics_meta m ON s.metadata_id = m.id
        WHERE {" AND ".join(conditions)}
        ORDER BY m.statistic_id, s.start_ts
    """
    return [
        StatisticRow(
            statistic_id=row[0],
            metadata_id=row[1],
            start_ts=row[2],
            state=row[3],
            sum=row[4],
        )
        for row in conn.execute(sql, params)
        if row[3] is not None and row[4] is not None
    ]


def _pairs(rows: Iterable[StatisticRow]) -> Iterable[tuple[StatisticRow, StatisticRow]]:
    previous: StatisticRow | None = None
    for row in rows:
        if previous is not None:
            yield previous, row
        previous = row


def _parse_time(value: str | None) -> float | None:
    if value is None:
        return None
    with sqlite3.connect(":memory:") as conn:
        return conn.execute("SELECT unixepoch(?)", (value,)).fetchone()[0]


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Path to home-assistant_v2.db")
    parser.add_argument("--prefs", type=Path, help="JSON output from energy/get_prefs")
    parser.add_argument("--statistic-id", action="append", default=[])
    parser.add_argument("--start", help="SQLite-compatible start timestamp")
    parser.add_argument("--end", help="SQLite-compatible end timestamp")
    parser.add_argument("--max-gap-hours", type=int, default=12)
    parser.add_argument("--max-delta-kwh", type=float, default=2.0)
    parser.add_argument("--apply", action="store_true", help="Insert interpolated gap rows")
    args = parser.parse_args()

    statistic_ids = list(args.statistic_id)
    if args.prefs:
        statistic_ids.extend(statistic_ids_from_energy_prefs(args.prefs))
    statistic_ids = list(dict.fromkeys(statistic_ids))
    if not statistic_ids:
        parser.error("Provide --statistic-id or --prefs")

    with sqlite3.connect(args.db) as conn:
        gaps = find_statistic_gaps(
            conn,
            statistic_ids,
            start_ts=_parse_time(args.start),
            end_ts=_parse_time(args.end),
            max_gap_hours=args.max_gap_hours,
        )
        deltas = find_suspicious_deltas(
            conn,
            statistic_ids,
            start_ts=_parse_time(args.start),
            end_ts=_parse_time(args.end),
            max_delta_kwh=args.max_delta_kwh,
        )
        result: dict[str, object] = {
            "statistic_ids": statistic_ids,
            "repairable_gaps": [gap.__dict__ for gap in gaps],
            "suspicious_deltas": [delta.__dict__ for delta in deltas],
        }
        if args.apply:
            with conn:
                result["inserted_rows"] = repair_statistic_gaps(conn, gaps)
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
