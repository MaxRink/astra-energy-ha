from pathlib import Path
import datetime as dt
import importlib.util
import sys
import types

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
                    "id": "ZT2_052/0",
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
    assert readings[0].meter_id == "ZT2_052_0"
    assert readings[0].raw_meter_id == "ZT2_052_0"
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
                    "v01": "1EBZ0103002978/0",
                    "v02": "5.517,247",
                    "v03": "kWh",
                    "v04": "2.432,418",
                    "v05": "19.06.2026",
                    "v06": "Strom VGB",
                    "v07": "Wohnung Strom",
                },
                {
                    "v01": "ZT1_052/0",
                    "v02": "4.695,978",
                    "v03": "kWh",
                    "v04": "1.605,326",
                    "v05": "17.06.2026",
                    "v06": "Strom T1 (Netzbezug)",
                    "v07": "Wohnung Netzstrom",
                },
                {
                    "v01": "ZT2_052/0",
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
    assert readings[0].meter_id == "1EBZ0103002978_0"
    assert readings[0].grid_kwh_total == 4774.064
    assert readings[0].solar_kwh_total == 743.183
    assert readings[0].total_kwh == 5517.247
    assert readings[0].raw["raw_grid_kwh_total"] == 4695.978
    assert readings[0].raw["grid_source"] == "derived_total_minus_solar"
    assert readings[0].raw["channels"]["grid"]["raw_meter_id"] == "ZT1_052_0"
    assert readings[0].raw["channels"]["solar"]["raw_meter_id"] == "ZT2_052_0"


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
    assert points[0]["timestamp"] == dt.datetime(2026, 6, 19, 0, 15, tzinfo=dt.UTC)


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
    )

    assert reading.meter_id == "meter_1"
    assert reading.grid_kwh_total == 87.0
    assert reading.solar_kwh_total == 23.0
    assert reading.total_kwh == 110.0
    assert reading.power_w == 40000.0
    assert reading.raw["grid_source"] == "derived_total_minus_solar"


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
            "sum": 104.0,
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
        sum_offset=4774.064,
    )

    assert rows == [
        {
            "start": dt.datetime(2026, 6, 19, 0, 15, tzinfo=dt.UTC),
            "state": 4784.3,
            "sum": 10.235999999999876,
        }
    ]


def test_statistics_ids_match_suggested_entity_ids() -> None:
    reading = astra_api.AstraMeterReading(
        meter_id="1EBZ0103002978_0",
        meter_name="1EBZ0103002978/0",
        timestamp=None,
        power_w=None,
        imported_kwh_total=None,
    )

    assert statistics._sensor_statistic_id(reading, "imported_energy") == (
        "sensor.astra_grid_energy"
    )
    assert statistics._sensor_statistic_id(reading, "solar_energy") == ("sensor.astra_solar_energy")
    assert statistics._sensor_statistic_id(reading, "total_energy") == ("sensor.astra_total_energy")


def test_reporting_error_payload() -> None:
    payload = reporting.error_payload(RuntimeError("boom"))
    assert payload["type"] == "RuntimeError"
    assert payload["message"] == "boom"
    assert "timestamp" in payload


def test_reporting_count_summary() -> None:
    assert reporting.summarize_counts({"b": 2, "a": 1}) == "a: 1, b: 2"
    assert reporting.summarize_counts({}) == "no readings"
