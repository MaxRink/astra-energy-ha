from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from tools.ha_energy_recorder_audit import (
    delete_suspicious_rows,
    find_statistic_gaps,
    find_suspicious_deltas,
    find_suspicious_rows,
    repair_counter_resets,
    repair_suspicious_rows,
    repair_statistic_gaps,
    statistic_ids_from_energy_prefs,
)


def test_energy_prefs_extracts_unique_device_consumption_ids(tmp_path: Path) -> None:
    prefs = tmp_path / "energy_prefs.json"
    prefs.write_text(
        """
        {
          "device_consumption": [
            {"stat_consumption": "sensor.server_energy"},
            {"stat_consumption": "sensor.server_energy"},
            {"stat_consumption": "sensor.klimaanlage_energy"},
            {"stat_rate": "sensor.power_only"}
          ]
        }
        """,
        encoding="utf-8",
    )

    assert statistic_ids_from_energy_prefs(prefs) == [
        "sensor.server_energy",
        "sensor.klimaanlage_energy",
    ]


def test_gap_audit_and_repair_distributes_recorder_outage_delta() -> None:
    conn = _fixture_db()
    statistic_ids = ["sensor.klimaanlage_energy"]

    gaps = find_statistic_gaps(conn, statistic_ids, max_gap_hours=12)
    assert len(gaps) == 1
    assert gaps[0].missing_hours == 7
    assert gaps[0].delta_sum == 3.5

    deltas = find_suspicious_deltas(conn, statistic_ids, max_delta_kwh=2.0)
    assert len(deltas) == 1
    assert deltas[0].delta_sum == 3.5

    with conn:
        assert repair_statistic_gaps(conn, gaps) == 7

    assert find_statistic_gaps(conn, statistic_ids, max_gap_hours=12) == []
    assert find_suspicious_deltas(conn, statistic_ids, max_delta_kwh=2.0) == []
    rows = conn.execute(
        """
        SELECT start_ts, state, sum
        FROM statistics
        WHERE metadata_id = 1
        ORDER BY start_ts
        """
    ).fetchall()
    assert len(rows) == 9
    assert rows[1] == (1782403200.0, 335.8675, 107.5675)
    assert rows[-1] == (1782428400.0, 338.93, 110.63)


def test_gap_repair_ignores_counter_decreases() -> None:
    conn = _fixture_db(next_state=330.0, next_sum=100.0)

    assert find_statistic_gaps(conn, ["sensor.klimaanlage_energy"], max_gap_hours=12) == []
    deltas = find_suspicious_deltas(conn, ["sensor.klimaanlage_energy"], max_delta_kwh=2.0)
    assert len(deltas) == 1
    assert deltas[0].delta_sum < 0


def test_suspicious_row_repair_deletes_middle_positive_outlier() -> None:
    conn = _fixture_db(rows=[
        (1, 1782399600.0, 100.0, 100.0),
        (1, 1782403200.0, 450.0, 450.0),
        (1, 1782406800.0, 101.0, 101.0),
    ])

    rows = find_suspicious_rows(conn, ["sensor.klimaanlage_energy"], max_delta_kwh=2.0)

    assert [(row.start_ts, row.reason) for row in rows] == [(1782403200.0, "middle_outlier")]
    with conn:
        assert delete_suspicious_rows(conn, rows) == 1
    assert find_suspicious_deltas(conn, ["sensor.klimaanlage_energy"], max_delta_kwh=2.0) == []
    assert conn.execute("SELECT start_ts FROM statistics ORDER BY start_ts").fetchall() == [
        (1782399600.0,),
        (1782406800.0,),
    ]


def test_suspicious_row_repair_deletes_middle_negative_outlier() -> None:
    conn = _fixture_db(rows=[
        (1, 1782399600.0, 100.0, 100.0),
        (1, 1782403200.0, 60.0, 60.0),
        (1, 1782406800.0, 101.0, 101.0),
    ])

    with conn:
        assert repair_suspicious_rows(
            conn,
            ["sensor.klimaanlage_energy"],
            max_delta_kwh=2.0,
        ) == 1

    assert find_suspicious_deltas(conn, ["sensor.klimaanlage_energy"], max_delta_kwh=2.0) == []
    assert conn.execute("SELECT start_ts FROM statistics ORDER BY start_ts").fetchall() == [
        (1782399600.0,),
        (1782406800.0,),
    ]


def test_suspicious_row_repair_keeps_unproven_negative_drop() -> None:
    conn = _fixture_db(rows=[
        (1, 1782399600.0, 450.0, 450.0),
        (1, 1782403200.0, 101.0, 101.0),
    ])

    assert find_suspicious_rows(conn, ["sensor.klimaanlage_energy"], max_delta_kwh=2.0) == []
    with conn:
        assert repair_suspicious_rows(
            conn,
            ["sensor.klimaanlage_energy"],
            max_delta_kwh=2.0,
        ) == 0


def test_counter_reset_repair_rebases_sum_after_gap() -> None:
    conn = _fixture_db(rows=[
        (1, 1782399600.0, 4870.488635076522, 134.9578995426582),
        (1, 1782633600.0, 4869.496, 0.0),
        (1, 1782637200.0, 4870.884, 1.38799999999992),
        (1, 1782640800.0, 4872.58, 3.0839999999998327),
    ])

    with conn:
        repairs = repair_counter_resets(conn, ["sensor.klimaanlage_energy"])

    assert repairs[0].deleted_rows == 1
    assert repairs[0].updated_rows == 2
    rows = conn.execute(
        """
        SELECT start_ts, state, sum
        FROM statistics
        ORDER BY start_ts
        """
    ).fetchall()
    assert rows[0] == (1782399600.0, 4870.488635076522, 134.9578995426582)
    assert rows[1] == pytest.approx((1782637200.0, 4870.884, 135.3532644661361))
    assert rows[2] == pytest.approx((1782640800.0, 4872.58, 137.04926446613602))


def test_counter_reset_repair_rebases_positive_state_after_sum_reset() -> None:
    conn = _fixture_db(rows=[
        (1, 1782399600.0, 822.4833649234745, 85.84510045733782),
        (1, 1782633600.0, 822.977, 0.0),
        (1, 1782637200.0, 822.977190876351, 0.00019087635098458122),
    ])

    with conn:
        repairs = repair_counter_resets(conn, ["sensor.klimaanlage_energy"])

    assert repairs[0].deleted_rows == 0
    assert repairs[0].updated_rows == 2
    sums = [
        row[0]
        for row in conn.execute(
            "SELECT sum FROM statistics ORDER BY start_ts"
        ).fetchall()
    ]
    assert sums == pytest.approx([
        85.84510045733782,
        86.33873553386336,
        86.33892641021434,
    ])


def _fixture_db(
    *,
    next_state: float = 338.93,
    next_sum: float = 110.63,
    rows: list[tuple[int, float, float, float]] | None = None,
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE statistics_meta (
            id INTEGER PRIMARY KEY,
            statistic_id TEXT NOT NULL
        );
        CREATE TABLE statistics (
            id INTEGER PRIMARY KEY,
            created_ts FLOAT,
            metadata_id INTEGER,
            start_ts FLOAT,
            mean FLOAT,
            min FLOAT,
            max FLOAT,
            state FLOAT,
            sum FLOAT
        );
        CREATE UNIQUE INDEX ix_statistics_statistic_id_start_ts
            ON statistics (metadata_id, start_ts);
        INSERT INTO statistics_meta(id, statistic_id)
        VALUES (1, 'sensor.klimaanlage_energy');
        """
    )
    conn.executemany(
        """
        INSERT INTO statistics(metadata_id, start_ts, state, sum)
        VALUES (?, ?, ?, ?)
        """,
        rows
        or [
            (1, 1782399600.0, 335.43, 107.13),
            (1, 1782428400.0, next_state, next_sum),
        ],
    )
    return conn
