from pathlib import Path
import json
import datetime as dt
import importlib.util
import sys
import types
import asyncio
from zoneinfo import ZoneInfo

import pytest

from tools.astra_mobile_probe import checksum, session_id
from tools.analyze_capture import endpoint_key, redact_headers

api_path = Path(__file__).parents[1] / "custom_components" / "astra_energy" / "api.py"
component_dir = api_path.parent

custom_components_pkg = types.ModuleType("custom_components")
custom_components_pkg.__path__ = []
astra_pkg = types.ModuleType("custom_components.astra_energy")
astra_pkg.__path__ = [str(component_dir)]
sys.modules.setdefault("custom_components", custom_components_pkg)
sys.modules.setdefault("custom_components.astra_energy", astra_pkg)

spec = importlib.util.spec_from_file_location("custom_components.astra_energy.api", api_path)
assert spec and spec.loader
astra_api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = astra_api
spec.loader.exec_module(astra_api)

homeassistant_mod = types.ModuleType("homeassistant")
homeassistant_components_mod = types.ModuleType("homeassistant.components")
homeassistant_config_entries_mod = types.ModuleType("homeassistant.config_entries")
homeassistant_const_mod = types.ModuleType("homeassistant.const")
homeassistant_core_mod = types.ModuleType("homeassistant.core")
homeassistant_exceptions_mod = types.ModuleType("homeassistant.exceptions")
homeassistant_helpers_mod = types.ModuleType("homeassistant.helpers")
homeassistant_aiohttp_mod = types.ModuleType("homeassistant.helpers.aiohttp_client")
homeassistant_update_coordinator_mod = types.ModuleType("homeassistant.helpers.update_coordinator")
homeassistant_util_mod = types.ModuleType("homeassistant.util")
homeassistant_dt_mod = types.ModuleType("homeassistant.util.dt")
homeassistant_unit_conversion_mod = types.ModuleType("homeassistant.util.unit_conversion")


class StubDataUpdateCoordinator:
    @classmethod
    def __class_getitem__(cls, _item):
        return cls


homeassistant_core_mod.HomeAssistant = object
homeassistant_config_entries_mod.ConfigEntryAuthFailed = RuntimeError
homeassistant_const_mod.UnitOfEnergy = types.SimpleNamespace(KILO_WATT_HOUR="kWh")
homeassistant_exceptions_mod.HomeAssistantError = RuntimeError
homeassistant_aiohttp_mod.async_get_clientsession = lambda _hass: None
homeassistant_update_coordinator_mod.DataUpdateCoordinator = StubDataUpdateCoordinator
homeassistant_update_coordinator_mod.UpdateFailed = RuntimeError
homeassistant_dt_mod.utcnow = lambda: dt.datetime(2026, 6, 20, 12, 0, 0)
homeassistant_dt_mod.as_utc = lambda value: value.astimezone(dt.UTC)
homeassistant_util_mod.dt = homeassistant_dt_mod
homeassistant_unit_conversion_mod.EnergyConverter = types.SimpleNamespace(UNIT_CLASS="energy")
sys.modules.setdefault("homeassistant", homeassistant_mod)
sys.modules.setdefault("homeassistant.components", homeassistant_components_mod)
sys.modules.setdefault("homeassistant.config_entries", homeassistant_config_entries_mod)
sys.modules.setdefault("homeassistant.const", homeassistant_const_mod)
sys.modules.setdefault("homeassistant.core", homeassistant_core_mod)
sys.modules.setdefault("homeassistant.exceptions", homeassistant_exceptions_mod)
sys.modules.setdefault("homeassistant.helpers", homeassistant_helpers_mod)
sys.modules.setdefault("homeassistant.helpers.aiohttp_client", homeassistant_aiohttp_mod)
sys.modules.setdefault(
    "homeassistant.helpers.update_coordinator", homeassistant_update_coordinator_mod
)
sys.modules.setdefault("homeassistant.util", homeassistant_util_mod)
sys.modules.setdefault("homeassistant.util.dt", homeassistant_dt_mod)
sys.modules.setdefault("homeassistant.util.unit_conversion", homeassistant_unit_conversion_mod)

reporting_path = component_dir / "reporting.py"
reporting_spec = importlib.util.spec_from_file_location(
    "custom_components.astra_energy.reporting", reporting_path
)
assert reporting_spec and reporting_spec.loader
reporting = importlib.util.module_from_spec(reporting_spec)
sys.modules[reporting_spec.name] = reporting
reporting_spec.loader.exec_module(reporting)

statistics_path = component_dir / "statistics.py"
statistics_spec = importlib.util.spec_from_file_location(
    "custom_components.astra_energy.statistics", statistics_path
)
assert statistics_spec and statistics_spec.loader
statistics = importlib.util.module_from_spec(statistics_spec)
sys.modules[statistics_spec.name] = statistics
statistics_spec.loader.exec_module(statistics)

web_session_path = component_dir / "web_session.py"
web_session_spec = importlib.util.spec_from_file_location(
    "custom_components.astra_energy.web_session", web_session_path
)
assert web_session_spec and web_session_spec.loader
web_session = importlib.util.module_from_spec(web_session_spec)
sys.modules[web_session_spec.name] = web_session
web_session_spec.loader.exec_module(web_session)


def test_endpoint_key_strips_query() -> None:
    assert endpoint_key("https://example.test/api/x?a=1") == "https://example.test/api/x"


def test_redact_headers() -> None:
    assert redact_headers({"Cookie": "secret", "Accept": "json"}) == {
        "Cookie": "<redacted>",
        "Accept": "json",
    }


def test_android_checksum() -> None:
    assert astra_api._checksum("get_ts", "") == "f5085fbbea6b0dbcab2287087a5709ba"
    assert checksum("get_ts", "") == astra_api._checksum("get_ts", "")


def test_android_session_id() -> None:
    assert (
        astra_api._session_id("user@example.test", "secret") == "063fe5677535abe6f556fbfdbd9a6978"
    )
    assert session_id("user@example.test", "secret") == astra_api._session_id(
        "user@example.test", "secret"
    )


def test_parse_number() -> None:
    assert astra_api._parse_number("1.234,56 kWh") == 1234.56
    assert astra_api._parse_number("12,5") == 12.5
    assert astra_api._parse_number(7) == 7.0
    assert astra_api._parse_number(None) is None
    assert astra_api._parse_number("") is None
    assert astra_api._parse_number("not a number") is None
    assert astra_api._parse_number("1-2") is None


def test_small_parsing_helpers_cover_missing_values() -> None:
    assert astra_api._total_or_zero(None) == 0.0
    assert astra_api._round_or_none(1.23456, 2) == 1.23
    assert astra_api._round_or_none(None) is None
    assert astra_api._cost_gross(10.0, 0.5) == 5.0
    assert astra_api._cost_gross(None, 0.5) is None
    assert astra_api._cost_gross(10.0, None) is None
    assert astra_api._cost_gross(-10.0, 0.5) is None
    assert astra_api._cost_gross(10.0, -0.5) is None
    assert astra_api._parse_datetime(None) is None
    assert astra_api._parse_datetime("not a date") is None
    assert astra_api._normalize_identifier(None) is None
    assert astra_api._normalize_identifier("   ") is None
    assert astra_api._normalize_identifier("TEST Solar/0") == "TEST_Solar_0"
    assert astra_api._raw_meter_id_from_row({"v01": "TEST_SOLAR_0"}) == "TEST_SOLAR_0"
    assert astra_api._raw_meter_id_from_row({"v01": "Strom VGB"}) is None


def test_parse_meter_stands_from_payload() -> None:
    client = astra_api.AstraClient(
        object(),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )
    readings = client._meter_stands_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "v01": "Main meter",
                    "v02": "1.234,5",
                    "v03": "kWh",
                    "v04": "12,3",
                    "v05": "20.06.2026",
                    "v06": "Strom",
                    "v07": "Account",
                }
            ],
        }
    )
    assert len(readings) == 1
    assert readings[0].meter_name == "Main meter"
    assert readings[0].imported_kwh_total == 1234.5
    assert readings[0].grid_kwh_total == 1234.5
    assert readings[0].meter_id.startswith("derived_")
    assert readings[0].raw["interval_consumption"] == 12.3


def test_parse_meter_skips_non_rows_and_non_energy_values() -> None:
    client = astra_api.AstraClient(
        object(),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )

    assert client._meter_stands_from_payload(
        {
            "auth": "1",
            "data": [
                "bad",
                {"v01": "No unit", "v02": "1.0", "v03": "EUR"},
                {"v01": "No value", "v02": "", "v03": "kWh"},
            ],
        }
    ) == []


def test_parse_meter_uses_raw_meter_id_when_available() -> None:
    client = astra_api.AstraClient(
        object(),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )
    readings = client._meter_stands_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "id": "TEST_SOLAR/0",
                    "v01": "Main meter",
                    "v02": "1.234,5",
                    "v03": "kWh",
                    "v05": "20.06.2026",
                    "v06": "Strom",
                    "v07": "Account",
                }
            ],
        }
    )
    assert readings[0].meter_id == "TEST_SOLAR_0"
    assert readings[0].raw_meter_id == "TEST_SOLAR_0"
    assert readings[0].legacy_meter_id.startswith("derived_")


def test_parse_combines_total_grid_and_solar_rows() -> None:
    client = astra_api.AstraClient(
        object(),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )
    readings = client._meter_stands_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "v01": "TEST_TOTAL/0",
                    "v02": "5.517,247",
                    "v03": "kWh",
                    "v04": "2.432,418",
                    "v05": "19.06.2026",
                    "v06": "Strom VGB",
                    "v07": "Wohnung Strom",
                },
                {
                    "v01": "TEST_GRID/0",
                    "v02": "4.695,978",
                    "v03": "kWh",
                    "v04": "1.605,326",
                    "v05": "17.06.2026",
                    "v06": "Strom T1 (Netzbezug)",
                    "v07": "Wohnung Netzstrom",
                },
                {
                    "v01": "TEST_SOLAR/0",
                    "v02": "743,183",
                    "v03": "kWh",
                    "v04": "286,016",
                    "v05": "17.06.2026",
                    "v06": "Strom T2 (Objektbezug)",
                    "v07": "Wohnung Objektstrom PV",
                },
            ],
        }
    )
    assert len(readings) == 1
    assert readings[0].meter_id == "TEST_TOTAL_0"
    assert readings[0].grid_kwh_total == 4774.064
    assert readings[0].solar_kwh_total == 743.183
    assert readings[0].total_kwh == 5517.247
    assert readings[0].raw["raw_grid_kwh_total"] == 4695.978
    assert readings[0].raw["grid_source"] == "derived_total_minus_solar"
    assert readings[0].raw["channels"]["grid"]["raw_meter_id"] == "TEST_GRID_0"
    assert readings[0].raw["channels"]["solar"]["raw_meter_id"] == "TEST_SOLAR_0"


def test_channel_classification_and_ungrouped_reading() -> None:
    assert astra_api._meter_channel_kind("x", "other", "misc") == "generic"
    reading = astra_api._reading_from_channel(
        {
            "raw_meter_id": None,
            "legacy_meter_id": "legacy",
            "total": 12.0,
            "meter_name": "Generic",
            "timestamp": None,
            "unit": "kWh",
            "interval_consumption": None,
            "medium": "other",
            "account": "misc",
            "row": {},
        }
    )
    assert reading.meter_id == "legacy"
    assert reading.unsmoothed_total_kwh == 12.0


def test_energy_balance_values_from_payload() -> None:
    values = astra_api._energy_balance_values_from_payload(
        {
            "auth": "1",
            "data": [
                {"v01": "Netzbezug", "v02": "399,000", "v03": "kWh"},
                {"v01": "PV-Bezug", "v02": "20,790", "v03": "kWh"},
                {"v01": "Gesamtbezug", "v02": "423,591", "v03": "kWh"},
            ],
        }
    )
    assert values == {
        "grid_kwh_total": 402.801,
        "solar_kwh_total": 20.79,
        "total_kwh": 423.591,
    }


def test_iter_months() -> None:
    import datetime as dt

    assert astra_api._iter_months(dt.date(2025, 12, 31), dt.date(2026, 2, 1)) == [
        (2025, 12),
        (2026, 1),
        (2026, 2),
    ]
    assert astra_api._iter_days(dt.date(2026, 1, 1), dt.date(2026, 1, 3)) == [
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 2),
        dt.date(2026, 1, 3),
    ]
    assert astra_api._previous_month(dt.date(2026, 1, 20)) == dt.date(2025, 12, 1)
    assert astra_api._previous_month(dt.date(2026, 6, 20)) == dt.date(2026, 5, 1)


def test_daily_interval_values_derive_grid_from_total_minus_solar() -> None:
    points = astra_api._daily_interval_values_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "_lvb_lbl_14h": "00:15,00:30",
                    "_lvb_ttl": "Gesamtbezug,Netzbezug,Objektbezug,PV-Bezug,Batterie-Bezug",
                    "_lvb_vll_14h": "10.0,2.0;9.0,1.0;3.0,1.0;3.0,1.0;0.0,0.0",
                }
            ],
        },
        dt.date(2026, 6, 19),
    )

    assert [point["grid_kwh"] for point in points] == [7.0, 1.0]
    assert [point["raw_grid_kwh"] for point in points] == [9.0, 1.0]
    assert points[0]["timestamp"] == dt.datetime(2026, 6, 18, 22, 15, tzinfo=dt.UTC)
    assert points[0]["timestamp"].astimezone(ZoneInfo("Europe/Berlin")) == dt.datetime(
        2026,
        6,
        19,
        0,
        15,
        tzinfo=ZoneInfo("Europe/Berlin"),
    )


def test_empty_interval_payloads_and_series_are_reported() -> None:
    assert astra_api._daily_interval_values_and_report_from_payload(
        {"auth": "1", "data": []},
        dt.date(2026, 6, 19),
    ) == ([], {"empty_payload": 1})
    assert astra_api._daily_interval_values_and_report_from_payload(
        {"auth": "1", "data": [{}]},
        dt.date(2026, 6, 19),
    ) == ([], {"empty_series": 1})
    assert astra_api._split_csv_text("0") == []
    assert astra_api._split_15m_series("0") == []
    assert astra_api._series_value({}, "Gesamtbezug", 0) is None
    assert astra_api._series_value({"gesamtbezug": [1.0]}, "Gesamtbezug", 2) is None


def test_daily_interval_spike_is_redistributed_from_fixture() -> None:
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "astra_energy_spike_day.json").read_text()
    )

    points, report = astra_api._daily_interval_values_and_report_from_payload(
        payload,
        dt.date(2026, 6, 15),
    )

    assert len(points) == 4
    assert report["total_kwh_redistributed"] == 1
    assert report["total_kwh_redistributed_buckets"] == 3
    assert round(sum(point["total_kwh"] for point in points), 6) == 20
    assert max(point["total_kwh"] for point in points) <= 12.5
    assert [round(point["grid_kwh"], 6) for point in points] == [
        round(point["total_kwh"], 6) for point in points
    ]
    assert [point["unsmoothed_total_kwh"] for point in points] == [0.0, 0.0, 20.0, 0.0]


def test_daily_interval_spike_can_be_rejected_as_missing_data() -> None:
    points, report = astra_api._daily_interval_values_and_report_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "_lvb_lbl_14h": "00:15",
                    "_lvb_ttl": "Gesamtbezug,Netzbezug,Objektbezug,PV-Bezug,Batterie-Bezug",
                    "_lvb_vll_14h": "20.0;20.0;0.0;0.0;0.0",
                }
            ],
        },
        dt.date(2026, 6, 15),
        max_average_kw=50.0,
    )

    assert points[0]["valid"] is False
    assert points[0]["anomalies"] == ["total_kwh_spike"]
    assert report["total_kwh_rejected"] == 1


def test_daily_interval_profiled_smoothing_uses_nearby_days() -> None:
    points = []
    for day in (dt.date(2026, 6, 14), dt.date(2026, 6, 15), dt.date(2026, 6, 16)):
        for minute, total in ((15, 0.0), (30, 2.0), (45, 4.0)):
            if day == dt.date(2026, 6, 15):
                total = 20.0 if minute == 45 else 0.0
            points.append(
                {
                    "timestamp": dt.datetime.combine(
                        day,
                        dt.time(0, minute),
                        tzinfo=dt.UTC,
                    ),
                    "total_kwh": total,
                    "solar_kwh": 0.0,
                    "grid_kwh": total,
                    "unsmoothed_total_kwh": total,
                    "unsmoothed_solar_kwh": 0.0,
                    "unsmoothed_grid_kwh": total,
                }
            )

    sanitized, report = astra_api._sanitize_interval_points(
        points,
        max_average_kw=50.0,
        smooth_anomalies=True,
        redistribution_window=3,
        smoothing_lookaround_days=1,
    )

    spike_day = [point for point in sanitized if point["timestamp"].date() == dt.date(2026, 6, 15)]
    assert report["total_kwh_redistributed"] == 1
    assert [round(point["total_kwh"], 3) for point in spike_day] == [0.0, 6.667, 13.333]
    assert [point["unsmoothed_total_kwh"] for point in spike_day] == [0.0, 0.0, 20.0]


def test_daily_interval_catchup_after_flat_gap_is_redistributed() -> None:
    points, report = astra_api._daily_interval_values_and_report_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "_lvb_lbl_14h": "00:15,00:30,00:45",
                    "_lvb_ttl": "Gesamtbezug,Netzbezug,Objektbezug,PV-Bezug,Batterie-Bezug",
                    "_lvb_vll_14h": "0.0,0.0,8.0;0.0,0.0,8.0;0.0,0.0,0.0;0.0,0.0,0.0;0.0,0.0,0.0",
                }
            ],
        },
        dt.date(2026, 6, 15),
        max_average_kw=50.0,
    )

    assert report["total_kwh_catchup_redistributed"] == 1
    assert [round(point["total_kwh"], 6) for point in points] == [
        round(8.0 / 3.0, 6),
        round(8.0 / 3.0, 6),
        round(8.0 / 3.0, 6),
    ]
    assert [point["unsmoothed_total_kwh"] for point in points] == [0.0, 0.0, 8.0]


def test_daily_interval_catchup_requires_at_least_two_flat_buckets() -> None:
    points, report = astra_api._daily_interval_values_and_report_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "_lvb_lbl_14h": "00:15,00:30",
                    "_lvb_ttl": "Gesamtbezug,Netzbezug,Objektbezug,PV-Bezug,Batterie-Bezug",
                    "_lvb_vll_14h": "0.0,8.0;0.0,8.0;0.0,0.0;0.0,0.0;0.0,0.0",
                }
            ],
        },
        dt.date(2026, 6, 15),
        max_average_kw=50.0,
    )

    assert "total_kwh_catchup_redistributed" not in report
    assert [point["total_kwh"] for point in points] == [0.0, 8.0]


def test_interval_catchup_can_redistribute_across_midnight() -> None:
    previous_day = dt.date(2026, 6, 18)
    current_day = dt.date(2026, 6, 19)
    raw_points = [
        {
            "timestamp": dt.datetime.combine(previous_day, dt.time(23, 30), tzinfo=dt.UTC),
            "total_kwh": 0.0,
            "solar_kwh": 0.0,
            "grid_kwh": 0.0,
            "unsmoothed_total_kwh": 0.0,
            "unsmoothed_solar_kwh": 0.0,
            "unsmoothed_grid_kwh": 0.0,
        },
        {
            "timestamp": dt.datetime.combine(previous_day, dt.time(23, 45), tzinfo=dt.UTC),
            "total_kwh": 0.0,
            "solar_kwh": 0.0,
            "grid_kwh": 0.0,
            "unsmoothed_total_kwh": 0.0,
            "unsmoothed_solar_kwh": 0.0,
            "unsmoothed_grid_kwh": 0.0,
        },
        {
            "timestamp": dt.datetime.combine(current_day, dt.time(0, 15), tzinfo=dt.UTC),
            "total_kwh": 9.0,
            "solar_kwh": 0.0,
            "grid_kwh": 9.0,
            "unsmoothed_total_kwh": 9.0,
            "unsmoothed_solar_kwh": 0.0,
            "unsmoothed_grid_kwh": 9.0,
        },
    ]

    sanitized, report = astra_api._sanitize_interval_points(raw_points, max_average_kw=50.0)

    assert report["total_kwh_catchup_redistributed"] == 1
    assert [point["timestamp"].date() for point in sanitized] == [
        previous_day,
        previous_day,
        current_day,
    ]
    assert [point["total_kwh"] for point in sanitized] == [3.0, 3.0, 3.0]


def test_delayed_interval_run_after_long_gap_is_redistributed() -> None:
    start = dt.datetime(2026, 6, 15, 12, 15, tzinfo=dt.UTC)
    raw_points = []
    for index in range(12):
        raw_points.append(
            {
                "timestamp": start + dt.timedelta(minutes=15 * index),
                "total_kwh": 0.0 if index < 8 else 2.0,
                "solar_kwh": 0.0,
                "grid_kwh": 0.0 if index < 8 else 2.0,
                "unsmoothed_total_kwh": 0.0 if index < 8 else 2.0,
                "unsmoothed_solar_kwh": 0.0,
                "unsmoothed_grid_kwh": 0.0 if index < 8 else 2.0,
            }
        )

    sanitized, report = astra_api._sanitize_interval_points(raw_points, max_average_kw=50.0)

    assert report["total_kwh_delayed_run_redistributed"] == 1
    assert round(sum(point["total_kwh"] for point in sanitized), 6) == 8.0
    assert max(point["total_kwh"] for point in sanitized) < 1.0
    assert [point["unsmoothed_total_kwh"] for point in sanitized[-4:]] == [2.0, 2.0, 2.0, 2.0]


def test_delayed_interval_run_respects_smoothing_toggle_and_minimum() -> None:
    start = dt.datetime(2026, 6, 15, 12, 15, tzinfo=dt.UTC)
    raw_points = [
        {
            "timestamp": start + dt.timedelta(minutes=15 * index),
            "total_kwh": 0.0 if index < 8 else 0.2,
            "solar_kwh": 0.0,
            "grid_kwh": 0.0 if index < 8 else 0.2,
        }
        for index in range(9)
    ]

    disabled, disabled_report = astra_api._sanitize_interval_points(
        [{**point} for point in raw_points],
        max_average_kw=50.0,
        smooth_anomalies=False,
    )
    below_minimum, below_minimum_report = astra_api._sanitize_interval_points(
        [{**point} for point in raw_points],
        max_average_kw=50.0,
        smooth_anomalies=True,
    )

    assert "total_kwh_delayed_run_redistributed" not in disabled_report
    assert "total_kwh_delayed_run_redistributed" not in below_minimum_report
    assert disabled[-1]["total_kwh"] == 0.2
    assert below_minimum[-1]["total_kwh"] == 0.2


def test_profiled_smoothing_ignores_out_of_window_days() -> None:
    timestamp = dt.datetime(2026, 6, 15, 0, 15, tzinfo=dt.UTC)
    weights = astra_api._redistribution_weights(
        [
            {"timestamp": timestamp, "total_kwh": 0.0, "solar_kwh": 0.0, "valid": True},
            {
                "timestamp": timestamp + dt.timedelta(days=10),
                "total_kwh": 4.0,
                "solar_kwh": 0.0,
                "valid": True,
            },
        ],
        [0],
        ("solar_kwh",),
        key="total_kwh",
        lookaround_days=1,
    )

    assert weights == [1.0]


def test_smoothing_falls_back_to_other_channel_then_equal_weights() -> None:
    timestamps = [
        dt.datetime(2026, 6, 15, 0, 15, tzinfo=dt.UTC),
        dt.datetime(2026, 6, 15, 0, 30, tzinfo=dt.UTC),
    ]
    other_channel = [
        {"timestamp": timestamps[0], "total_kwh": 0.0, "solar_kwh": 1.0, "valid": True},
        {"timestamp": timestamps[1], "total_kwh": 20.0, "solar_kwh": 3.0, "valid": True},
    ]
    assert astra_api._redistribution_weights(
        other_channel,
        [0, 1],
        ("solar_kwh",),
        key="total_kwh",
        lookaround_days=0,
    ) == [0.25, 0.75]

    equal = [
        {"timestamp": timestamps[0], "total_kwh": 0.0, "solar_kwh": 0.0, "valid": True},
        {"timestamp": timestamps[1], "total_kwh": 20.0, "solar_kwh": 0.0, "valid": True},
    ]
    assert astra_api._redistribution_weights(
        equal,
        [0, 1],
        ("solar_kwh",),
        key="total_kwh",
        lookaround_days=0,
    ) == [0.5, 0.5]


def test_interval_sanitizer_rejects_negative_values() -> None:
    sanitized, report = astra_api._sanitize_interval_points(
        [
            {
                "timestamp": dt.datetime(2026, 6, 15, 0, 15, tzinfo=dt.UTC),
                "total_kwh": -1.0,
                "solar_kwh": 0.0,
                "grid_kwh": -1.0,
                "raw_grid_kwh": -1.0,
                "unsmoothed_total_kwh": -1.0,
                "unsmoothed_solar_kwh": 0.0,
                "unsmoothed_grid_kwh": -1.0,
            },
            {
                "timestamp": dt.datetime(2026, 6, 15, 0, 30, tzinfo=dt.UTC),
                "total_kwh": 10.0,
                "solar_kwh": 0.0,
                "grid_kwh": 10.0,
            },
        ],
        max_average_kw=20.0,
    )

    assert sanitized[0]["valid"] is False
    assert sanitized[0]["unsmoothed_total_kwh"] == 0.0
    assert sanitized[0]["unsmoothed_grid_kwh"] == 0.0
    assert sanitized[1]["valid"] is True
    assert report["total_kwh_negative_rejected"] == 1
    assert report["raw_grid_kwh_negative_rejected"] == 1


def test_daily_interval_clamps_solar_to_total() -> None:
    points = astra_api._daily_interval_values_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "_lvb_lbl_14h": "00:15",
                    "_lvb_ttl": "Gesamtbezug,Netzbezug,Objektbezug,PV-Bezug,Batterie-Bezug",
                    "_lvb_vll_14h": "1.0;0.0;2.0;2.0;0.0",
                }
            ],
        },
        dt.date(2026, 6, 15),
    )

    assert points[0]["total_kwh"] == 1.0
    assert points[0]["solar_kwh"] == 1.0
    assert points[0]["grid_kwh"] == 0.0


def test_overview_metrics_derive_grid_and_keep_raw_grid() -> None:
    metrics = astra_api._overview_metrics_from_payload(
        {
            "auth": "1",
            "data": [
                {"v01": "str_mtr_vbo_vb_strom_gesbez", "v02": "2432.418", "v03": "kWh"},
                {"v01": "str_mtr_vbo_vb_strom_t1", "v02": "1605.326", "v03": "kWh"},
                {"v01": "str_mtr_vbo_strom_t2", "v02": "286.016", "v03": "kWh"},
                {"v01": "str_mtr_vbo_vmco_strom_pv", "v02": "0.161", "v03": "t"},
                {"v01": "str_mtr_vbo_autarkiegrad", "v02": "11.759", "v03": "%"},
            ],
        }
    )

    assert metrics["current_year_total_kwh"] == 2432.418
    assert metrics["current_year_raw_grid_kwh"] == 1605.326
    assert metrics["current_year_solar_kwh"] == 286.016
    assert metrics["current_year_grid_kwh"] == 2146.402
    assert metrics["pv_co2_savings_t"] == 0.161
    assert metrics["autarky_percent"] == 11.759


def test_overview_metrics_fall_back_to_raw_grid() -> None:
    metrics = astra_api._overview_metrics_from_payload(
        {
            "auth": "1",
            "data": [
                "bad",
                {"v01": "str_mtr_vbo_vb_strom_t1", "v02": "1605.326", "v03": "kWh"},
                {"v01": "ignored", "v02": "", "v03": "kWh"},
            ],
        }
    )

    assert metrics["current_year_grid_kwh"] == 1605.326


def test_monthly_metrics_derive_grid_from_total_minus_solar() -> None:
    metrics = astra_api._monthly_metrics_from_payload(
        {
            "auth": "1",
            "data": [
                {
                    "_hvb_ttl": "Gesamtbezug,Netzbezug,Objektbezug,PV-Bezug,Batterie-Bezug",
                    "_hvb_vll": (
                        "423.591,406.371;"
                        "402.801,376.63;"
                        "20.79,29.741;"
                        "0,0;"
                        "0,0"
                    ),
                }
            ],
        },
        0,
    )

    assert metrics["current_month_total_kwh"] == 423.591
    assert metrics["current_month_raw_grid_kwh"] == 402.801
    assert metrics["current_month_solar_kwh"] == 20.79
    assert metrics["current_month_grid_kwh"] == 402.801


def test_monthly_metrics_empty_and_pv_fallback() -> None:
    assert astra_api._monthly_metrics_from_payload({"data": []}, 0) == {}
    assert astra_api._monthly_metrics_from_payload({"data": [{}]}, 0) == {}
    assert astra_api._monthly_metrics_from_payload(
        {
            "data": [
                {
                    "_vb_ttl": "Gesamtbezug,Netzbezug,Objektbezug,PV-Bezug",
                    "_vb_vll": "10.0;9.0;0.0;1.0",
                }
            ],
        },
        0,
    )["current_month_solar_kwh"] == 1.0
    raw_only = astra_api._monthly_metrics_from_payload(
        {
            "data": [
                {
                    "_vb_ttl": "Netzbezug",
                    "_vb_vll": "9.0",
                }
            ],
        },
        0,
    )
    assert raw_only["current_month_grid_kwh"] == 9.0
    assert astra_api._monthly_metrics_from_payload(
        {
            "data": [
                {
                    "_vb_ttl": "Gesamtbezug",
                    "_vb_vll": "9.0",
                }
            ],
        },
        1,
    ) == {}


def test_interval_point_reading_uses_cumulative_totals() -> None:
    reading = astra_api._reading_from_interval_point(
        {
            "timestamp": dt.datetime(2026, 6, 19, 0, 15, tzinfo=dt.UTC),
            "label": "00:15",
            "total_kwh": 10.0,
            "grid_kwh": 7.0,
            "solar_kwh": 3.0,
            "raw_grid_kwh": 9.0,
        },
        {"total": 110.0, "grid": 87.0, "solar": 23.0},
        template=astra_api.AstraMeterReading(
            meter_id="meter_1",
            meter_name="Main meter",
            timestamp=None,
            power_w=None,
            imported_kwh_total=None,
            raw_meter_id="raw_1",
            legacy_meter_id="legacy_1",
        ),
        grid_price_net=0.294,
        grid_price_gross=0.35,
        solar_price_net=0.21,
        solar_price_gross=0.25,
        tax_rate=0.19,
        period_totals={
            "current_month_grid_kwh": 7.0,
            "current_month_solar_kwh": 3.0,
            "current_month_total_kwh": 10.0,
            "current_month_raw_grid_kwh": 9.0,
            "current_month_grid_cost_gross_eur": 2.45,
            "current_month_solar_cost_gross_eur": 0.75,
            "current_month_total_cost_gross_eur": 3.2,
            "current_year_grid_kwh": 70.0,
            "current_year_solar_kwh": 30.0,
            "current_year_total_kwh": 100.0,
            "current_year_raw_grid_kwh": 90.0,
            "current_year_grid_cost_gross_eur": 24.5,
            "current_year_solar_cost_gross_eur": 7.5,
            "current_year_total_cost_gross_eur": 32.0,
        },
    )

    assert reading.meter_id == "meter_1"
    assert reading.grid_kwh_total == 87.0
    assert reading.solar_kwh_total == 23.0
    assert reading.total_kwh == 110.0
    assert reading.unsmoothed_grid_kwh_total == 87.0
    assert reading.raw_grid_kwh_total is None
    assert reading.grid_price_net_eur_per_kwh == 0.294
    assert reading.grid_price_gross_eur_per_kwh == 0.35
    assert reading.solar_price_net_eur_per_kwh == 0.21
    assert reading.tax_rate == 0.19
    assert reading.grid_cost_total_gross_eur == 30.45
    assert reading.solar_cost_total_gross_eur == 5.75
    assert reading.total_cost_total_gross_eur == 36.2
    assert reading.current_month_total_kwh == 10.0
    assert reading.current_month_total_cost_gross_eur == 3.2
    assert reading.current_year_raw_grid_kwh == 90.0
    assert reading.current_year_total_cost_gross_eur == 32.0
    assert reading.power_w == 40000.0
    assert reading.raw["grid_source"] == "derived_total_minus_solar"
    assert reading.raw["period_totals"]["current_year_total_kwh"] == 100.0


def test_interval_period_totals_use_interval_start_period() -> None:
    month_totals: dict[tuple[int, int], dict[str, float]] = {}
    year_totals: dict[int, dict[str, float]] = {}

    first = astra_api._update_interval_period_totals(
        {
            "timestamp": dt.datetime(2026, 7, 1, 0, 0, tzinfo=dt.UTC),
            "total_kwh": 1.0,
            "grid_kwh": 0.75,
            "solar_kwh": 0.25,
            "raw_grid_kwh": 0.8,
        },
        month_totals,
        year_totals,
        grid_price_gross=0.35,
        solar_price_gross=0.25,
    )
    second = astra_api._update_interval_period_totals(
        {
            "timestamp": dt.datetime(2026, 7, 1, 0, 15, tzinfo=dt.UTC),
            "total_kwh": 2.0,
            "grid_kwh": 1.5,
            "solar_kwh": 0.5,
            "raw_grid_kwh": 1.6,
        },
        month_totals,
        year_totals,
        grid_price_gross=0.35,
        solar_price_gross=0.25,
    )

    assert first["current_month_total_kwh"] == 1.0
    assert first["current_month_raw_grid_kwh"] == 0.8
    assert first["current_month_total_cost_gross_eur"] == 0.325
    assert second["current_month_total_kwh"] == 3.0
    assert second["current_year_grid_cost_gross_eur"] == 0.7875


def test_reading_with_metrics_adds_prices_costs_and_raw_payload() -> None:
    client = astra_api.AstraClient(
        object(),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
        grid_price_net=0.294,
        solar_price_net=0.21,
        tax_rate=0.19,
    )
    reading = client._reading_with_metrics(
        astra_api.AstraMeterReading(
            meter_id="meter_1",
            meter_name="Main meter",
            timestamp=None,
            power_w=None,
            imported_kwh_total=100.0,
            raw={},
        ),
        overview_values={"current_year_grid_kwh": 10.0, "current_year_solar_kwh": 2.0},
        monthly_values={"current_month_grid_kwh": 1.0, "current_month_solar_kwh": 0.5},
    )

    assert reading.grid_price_gross_eur_per_kwh == 0.34986
    assert reading.solar_price_gross_eur_per_kwh == 0.2499
    assert reading.grid_cost_total_gross_eur == 34.986
    assert reading.current_month_total_cost_gross_eur == 0.4749
    assert reading.current_year_total_cost_gross_eur == 3.9984
    assert reading.raw["tariff"]["tax_rate"] == 0.19


def test_latest_reading_by_month_uses_latest_timestamp() -> None:
    older = astra_api.AstraMeterReading(
        meter_id="meter_1",
        meter_name="Main meter",
        timestamp=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        power_w=None,
        imported_kwh_total=1.0,
    )
    newer = astra_api.AstraMeterReading(
        meter_id="meter_1",
        meter_name="Main meter",
        timestamp=dt.datetime(2026, 6, 2, tzinfo=dt.UTC),
        power_w=None,
        imported_kwh_total=2.0,
    )
    missing = astra_api.AstraMeterReading(
        meter_id="meter_1",
        meter_name="Main meter",
        timestamp=None,
        power_w=None,
        imported_kwh_total=3.0,
    )

    assert astra_api._latest_reading_by_month([older, missing, newer]) == {
        dt.date(2026, 6, 1): newer
    }


def test_statistics_rows_align_interval_end_timestamps_to_hour() -> None:
    readings = [
        astra_api.AstraMeterReading(
            meter_id="meter_1",
            meter_name="Main meter",
            timestamp=dt.datetime(2026, 6, 19, 0, 15, tzinfo=dt.UTC),
            power_w=None,
            imported_kwh_total=101.0,
            grid_kwh_total=101.0,
        ),
        astra_api.AstraMeterReading(
            meter_id="meter_1",
            meter_name="Main meter",
            timestamp=dt.datetime(2026, 6, 19, 0, 45, tzinfo=dt.UTC),
            power_w=None,
            imported_kwh_total=103.0,
            grid_kwh_total=103.0,
        ),
        astra_api.AstraMeterReading(
            meter_id="meter_1",
            meter_name="Main meter",
            timestamp=dt.datetime(2026, 6, 19, 1, 0, tzinfo=dt.UTC),
            power_w=None,
            imported_kwh_total=104.0,
            grid_kwh_total=104.0,
        ),
    ]

    rows = statistics._statistics_rows(
        readings,
        "grid_kwh_total",
        align_to_hour=True,
    )

    assert rows == [
        {
            "start": dt.datetime(2026, 6, 19, 0, 0, tzinfo=dt.UTC),
            "state": 104.0,
            "sum": 3.0,
        }
    ]


def test_statistics_rows_apply_sum_offset_without_changing_state() -> None:
    rows = statistics._statistics_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 19, 0, 15, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=4784.3,
                grid_kwh_total=4784.3,
            )
        ],
        "grid_kwh_total",
        sum_start=4774.064,
    )

    assert rows == [
        {
            "start": dt.datetime(2026, 6, 19, 0, 15, tzinfo=dt.UTC),
            "state": 4784.3,
            "sum": 4774.064,
        }
    ]


def test_statistics_rows_never_decrease_sum_when_meter_state_drops() -> None:
    rows = statistics._statistics_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 19, 0, 0, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=200.0,
                grid_kwh_total=200.0,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 19, 1, 0, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=150.0,
                grid_kwh_total=150.0,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 19, 2, 0, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=175.0,
                grid_kwh_total=175.0,
            ),
        ],
        "grid_kwh_total",
    )

    assert [row["state"] for row in rows] == [200.0]
    assert [row["sum"] for row in rows] == [0.0]


def test_statistics_rows_skip_existing_recorder_state_rollbacks() -> None:
    rows = statistics._statistics_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 21, 16, 0, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=-380.0,
                grid_kwh_total=-380.0,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 21, 17, 0, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=0.9,
                grid_kwh_total=0.9,
            ),
        ],
        "grid_kwh_total",
        state_start=899.0,
        sum_start=899.0,
    )

    assert rows == []


def test_statistics_rows_skip_implausible_hourly_jump() -> None:
    rows = statistics._statistics_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 21, 15, 0, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=1000.0,
                grid_kwh_total=1000.0,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 21, 16, 0, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=1380.0,
                grid_kwh_total=1380.0,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 21, 17, 0, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=1001.0,
                grid_kwh_total=1001.0,
            ),
        ],
        "grid_kwh_total",
        max_hourly_delta=50.0,
    )

    assert [row["state"] for row in rows] == [1000.0, 1001.0]
    assert [row["sum"] for row in rows] == [0.0, 1.0]


def test_statistics_rows_skip_missing_timestamp_or_value() -> None:
    assert (
        statistics._statistics_rows(
            [
                astra_api.AstraMeterReading(
                    meter_id="meter_1",
                    meter_name="Main meter",
                    timestamp=None,
                    power_w=None,
                    imported_kwh_total=None,
                    grid_kwh_total=100.0,
                )
            ],
            "grid_kwh_total",
        )
        == []
    )
    assert (
        statistics._statistics_rows(
            [
                astra_api.AstraMeterReading(
                    meter_id="meter_1",
                    meter_name="Main meter",
                    timestamp=dt.datetime(2026, 6, 19, 1, 0, tzinfo=dt.UTC),
                    power_w=None,
                    imported_kwh_total=None,
                    grid_kwh_total=None,
                )
            ],
            "grid_kwh_total",
        )
        == []
    )


def test_statistics_rows_skip_missing_timestamp_or_value_mixed_input() -> None:
    rows = statistics._statistics_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 19, 1, 0),
                power_w=None,
                imported_kwh_total=None,
                grid_kwh_total=100.0,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 19, 2, 0),
                power_w=None,
                imported_kwh_total=None,
                grid_kwh_total=None,
            ),
        ],
        "grid_kwh_total",
    )

    assert len(rows) == 1
    assert rows[0]["state"] == 100.0


def test_interval_hour_start_handles_exact_hour() -> None:
    assert astra_api._interval_hour_start(dt.datetime(2026, 6, 19, 1, 0, tzinfo=dt.UTC)) == (
        dt.datetime(2026, 6, 19, 0, 0, tzinfo=dt.UTC)
    )
    assert astra_api._interval_hour_start(dt.datetime(2026, 6, 19, 1, 15, tzinfo=dt.UTC)) == (
        dt.datetime(2026, 6, 19, 1, 0, tzinfo=dt.UTC)
    )


def test_statistics_ids_match_suggested_entity_ids() -> None:
    reading = astra_api.AstraMeterReading(
        meter_id="TEST_TOTAL_0",
        meter_name="TEST_TOTAL/0",
        timestamp=None,
        power_w=None,
        imported_kwh_total=None,
    )

    assert statistics._sensor_statistic_id(reading, "imported_energy") == (
        "sensor.astra_grid_energy"
    )
    assert statistics._sensor_statistic_id(reading, "solar_energy") == ("sensor.astra_solar_energy")
    assert statistics._sensor_statistic_id(reading, "total_energy") == ("sensor.astra_total_energy")
    assert statistics._sensor_statistic_id(reading, "grid_energy_cost_total") == (
        "sensor.astra_grid_energy_cost_total"
    )
    assert statistics._sensor_statistic_id(reading, "solar_energy_cost_total") == (
        "sensor.astra_solar_energy_cost_total"
    )
    assert statistics._sensor_statistic_id(reading, "total_energy_cost_total") == (
        "sensor.astra_total_energy_cost_total"
    )
    assert statistics._sensor_statistic_id(reading, "current_month_total_cost") == (
        "sensor.astra_current_month_total_cost"
    )
    assert statistics._sensor_statistic_id(reading, "current_year_total_energy") == (
        "sensor.astra_current_year_total_energy"
    )
    assert statistics._sensor_statistic_id(reading, "grid_price") == (
        "sensor.astra_grid_energy_price"
    )


def test_unsmoothed_diagnostic_sensors_are_not_imported_to_recorder_statistics() -> None:
    assert "unsmoothed_imported_energy" not in statistics.STATISTIC_CHANNELS
    assert "unsmoothed_solar_energy" not in statistics.STATISTIC_CHANNELS
    assert "unsmoothed_total_energy" not in statistics.STATISTIC_CHANNELS


def test_statistics_channels_include_historical_derived_metrics() -> None:
    for channel in {
        "raw_grid_energy",
        "current_month_grid_energy",
        "current_month_solar_energy",
        "current_month_total_energy",
        "current_month_grid_cost",
        "current_month_solar_cost",
        "current_month_total_cost",
        "current_year_grid_energy",
        "current_year_solar_energy",
        "current_year_total_energy",
        "current_year_raw_grid_energy",
        "current_year_grid_cost",
        "current_year_solar_cost",
        "current_year_total_cost",
        "grid_price",
        "solar_price",
        "tax_rate",
        "autarky",
        "pv_co2_savings",
    }:
        assert channel in statistics.STATISTIC_CHANNELS


def test_period_and_measurement_statistics_are_state_only() -> None:
    assert statistics.STATISTIC_CHANNELS["current_month_total_energy"].has_sum
    assert statistics.STATISTIC_CHANNELS["current_month_total_energy"].allow_reset
    assert not statistics.STATISTIC_CHANNELS["current_year_total_cost"].has_sum
    assert not statistics.STATISTIC_CHANNELS["grid_price"].has_sum
    assert statistics.STATISTIC_CHANNELS["grid_price"].has_mean
    assert statistics.STATISTIC_CHANNELS["grid_energy_cost_total"].has_sum


def test_sum_statistics_rows_allow_period_resets() -> None:
    rows = statistics._statistics_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 30, 23, 45, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=None,
                current_month_total_kwh=400.0,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 7, 1, 0, 15, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=None,
                current_month_total_kwh=0.5,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 7, 1, 0, 30, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=None,
                current_month_total_kwh=0.8,
            ),
        ],
        "current_month_total_kwh",
        allow_reset=True,
    )

    assert [row["state"] for row in rows] == [400.0, 0.5, 0.8]
    assert [row["sum"] for row in rows] == [0.0, 0.5, 0.8]


def test_state_and_mean_statistics_rows_shape_values() -> None:
    rows = statistics._statistics_state_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 6, 30, 23, 45, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=None,
                current_month_total_kwh=400.0,
                tax_rate=0.19,
            ),
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 7, 1, 0, 15, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=None,
                current_month_total_kwh=0.5,
                tax_rate=0.19,
            ),
        ],
        "current_month_total_kwh",
        align_to_hour=True,
    )
    tax_rows = statistics._statistics_state_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 7, 1, 0, 15, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=None,
                tax_rate=0.19,
            )
        ],
        "tax_rate",
        value_multiplier=100.0,
    )
    mean_rows = statistics._statistics_mean_rows(
        [
            astra_api.AstraMeterReading(
                meter_id="meter_1",
                meter_name="Main meter",
                timestamp=dt.datetime(2026, 7, 1, 0, 15, tzinfo=dt.UTC),
                power_w=None,
                imported_kwh_total=None,
                tax_rate=0.19,
            )
        ],
        "tax_rate",
        value_multiplier=100.0,
    )

    assert [row["state"] for row in rows] == [400.0, 0.5]
    assert all(row["sum"] is None for row in rows)
    assert tax_rows[0]["state"] == 19.0
    assert mean_rows[0]["mean"] == 19.0
    assert "state" not in mean_rows[0]


class FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self._text = text
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False

    async def text(self, *_args, **_kwargs) -> str:
        return self._text


class FakeSession:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    def post(self, *_args, **_kwargs):
        if self.error is not None:
            raise self.error
        return self.response


class EndpointSession:
    def __init__(self, responses: dict[str, list[FakeResponse]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def post(self, url, **_kwargs):
        self.calls.append(url)
        return self.responses[url].pop(0)


class FakeGetSession:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def _verified_response(body: str, status: int = 200) -> FakeResponse:
    return FakeResponse(body + astra_api._md5(body), status=status)


def test_post_raw_wraps_unreachable_api() -> None:
    client = astra_api.AstraClient(
        FakeSession(error=OSError("network down")),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )

    with pytest.raises(astra_api.AstraApiError, match="network down"):
        asyncio.run(client._post_raw({"s_action": "get_ts"}))


def test_post_raw_reports_http_errors() -> None:
    client = astra_api.AstraClient(
        FakeSession(response=_verified_response("nope", status=500)),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )

    with pytest.raises(astra_api.AstraApiError, match="Astra HTTP 500"):
        asyncio.run(client._post_raw({"s_action": "get_ts"}))


def test_post_raw_rejects_short_and_bad_checksum_responses() -> None:
    short_client = astra_api.AstraClient(
        FakeSession(response=FakeResponse("short")),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )
    with pytest.raises(astra_api.AstraProtocolError, match="too short"):
        asyncio.run(short_client._post_raw({"s_action": "get_ts"}))

    checksum_client = astra_api.AstraClient(
        FakeSession(response=FakeResponse("body" + "0" * 32)),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )
    with pytest.raises(astra_api.AstraProtocolError, match="checksum"):
        asyncio.run(checksum_client._post_raw({"s_action": "get_ts"}))


def test_post_action_falls_back_between_mobile_endpoints() -> None:
    bad_url = "https://bad.example.test/csandroid.php"
    good_url = "https://good.example.test/csios.php"
    session = EndpointSession(
        {
            bad_url: [FakeResponse("")],
            good_url: [
                _verified_response("12345"),
                _verified_response(json.dumps({"auth": "1"})),
            ],
        }
    )
    client = astra_api.AstraClient(
        session,
        username="user@example.test",
        password="secret",
        base_url=f"{bad_url},{good_url}",
    )

    result = asyncio.run(client._post_action("auth_login", s_sid="sid"))

    assert json.loads(result) == {"auth": "1"}
    assert session.calls == [bad_url, good_url, good_url]


def test_login_reports_protocol_and_auth_errors() -> None:
    protocol_client = astra_api.AstraClient(
        object(),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )

    async def bad_json(*_args, **_kwargs):
        return "not-json"

    protocol_client._post_action = bad_json
    with pytest.raises(astra_api.AstraProtocolError, match="not JSON"):
        asyncio.run(protocol_client.async_login())

    auth_client = astra_api.AstraClient(
        object(),
        username="user@example.test",
        password="secret",
        base_url="https://example.test",
    )

    async def auth_failed(*_args, **_kwargs):
        return json.dumps({"auth": "0"})

    auth_client._post_action = auth_failed
    with pytest.raises(astra_api.AstraAuthError, match="authentication failed"):
        asyncio.run(auth_client.async_login())


def test_reporting_error_payload() -> None:
    payload = reporting.error_payload(RuntimeError("boom"))
    assert payload["type"] == "RuntimeError"
    assert payload["message"] == "boom"
    assert "timestamp" in payload


def test_reporting_count_summary() -> None:
    assert reporting.summarize_counts({"b": 2, "a": 1}) == "a: 1, b: 2"
    assert reporting.summarize_counts({}) == "no readings"


def test_web_graph_parser_and_classifier() -> None:
    html = (
        '<area TITLE="Gesamtbezug ist 100,50 kWh um 21.06.2026 12:15:00">'
        '<area TITLE="Gesamtbezug ist 0,50 kWh um 21.06.2026 12:15:00">'
    )

    points = web_session.parse_graph_points(html)

    assert len(points) == 1
    assert points[0].cumulative_kwh == 100.5
    assert points[0].interval_kwh == 0.5
    assert web_session.classify_web_response(html, len(points)) == ("ok", None)


def test_web_graph_parser_skips_unusable_values() -> None:
    assert web_session.parse_graph_points(
        '<area TITLE="Gesamtbezug ist - kWh um 21.06.2026 12:15:00">'
    ) == []
    assert web_session.parse_graph_points(
        '<area TITLE="Gesamtbezug ist -1,00 kWh um 21.06.2026 12:15:00">'
    ) == []


@pytest.mark.parametrize(
    ("html", "status"),
    [
        ('<form><div class="g-recaptcha"></div></form>', "login_required"),
        ("Ihre session ist abgelaufen", "expired"),
        ("", "invalid_response"),
        ("<html>no graph data here</html>", "no_data"),
    ],
)
def test_web_response_classifier_reports_actionable_states(html: str, status: str) -> None:
    classified, message = web_session.classify_web_response(html, 0)

    assert classified == status
    if status != "invalid_response":
        assert message


def test_web_session_check_reports_missing_configuration() -> None:
    status = asyncio.run(
        web_session.async_check_web_session(
            FakeGetSession(),
            session_id="",
            cookie="",
        )
    )

    assert status.status == "not_configured"
    assert status.as_dict()["status"] == "not_configured"


def test_web_session_check_reports_incomplete_configuration() -> None:
    missing_session = asyncio.run(
        web_session.async_check_web_session(
            FakeGetSession(),
            session_id="",
            cookie="sid=secret",
        )
    )
    assert missing_session.status == "missing_session_id"

    missing_cookie = asyncio.run(
        web_session.async_check_web_session(
            FakeGetSession(),
            session_id="abc",
            cookie="",
            graph_id="test_graph",
        )
    )
    assert missing_cookie.status == "missing_cookie"

    missing_graph = asyncio.run(
        web_session.async_check_web_session(
            FakeGetSession(),
            session_id="abc",
            cookie="sid=secret",
            graph_id="",
        )
    )
    assert missing_graph.status == "missing_graph_id"


def test_web_session_check_reports_unreachable_and_logged_out() -> None:
    unreachable = asyncio.run(
        web_session.async_check_web_session(
            FakeGetSession(error=OSError("network down")),
            session_id="abc",
            cookie="sid=secret",
            graph_id="test_graph",
        )
    )
    assert unreachable.status == "unreachable"
    assert "network down" in unreachable.message

    logged_out = asyncio.run(
        web_session.async_check_web_session(
            FakeGetSession(response=FakeResponse('<form action="csloginw.php">Passwort</form>')),
            session_id="abc",
            cookie="sid=secret",
            graph_id="test_graph",
        )
    )
    assert logged_out.status == "login_required"


def test_web_session_check_reports_http_errors() -> None:
    status = asyncio.run(
        web_session.async_check_web_session(
            FakeGetSession(response=FakeResponse("server error", status=503)),
            session_id="abc",
            cookie="sid=secret",
            graph_id="test_graph",
        )
    )

    assert status.status == "unreachable"
    assert status.message == "Astra web graph returned HTTP 503"
    assert status.response_bytes == len("server error")


def test_web_session_check_reports_valid_cookie_session() -> None:
    html = (
        '<area TITLE="Gesamtbezug ist 100,50 kWh um 21.06.2026 12:15:00">'
        '<area TITLE="Gesamtbezug ist 0,50 kWh um 21.06.2026 12:15:00">'
    )
    session = FakeGetSession(response=FakeResponse(html))

    status = asyncio.run(
        web_session.async_check_web_session(
            session,
            session_id="abc",
            cookie="sid=secret",
            graph_id="test_graph",
        )
    )

    assert status.status == "ok"
    assert status.point_count == 1
    assert session.calls[0][1]["headers"]["Cookie"] == "sid=secret"
