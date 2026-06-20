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
homeassistant_core_mod = types.ModuleType("homeassistant.core")
homeassistant_util_mod = types.ModuleType("homeassistant.util")
homeassistant_dt_mod = types.ModuleType("homeassistant.util.dt")
homeassistant_core_mod.HomeAssistant = object
homeassistant_dt_mod.utcnow = lambda: dt.datetime(2026, 6, 20, 12, 0, 0)
homeassistant_util_mod.dt = homeassistant_dt_mod
sys.modules.setdefault("homeassistant", homeassistant_mod)
sys.modules.setdefault("homeassistant.core", homeassistant_core_mod)
sys.modules.setdefault("homeassistant.util", homeassistant_util_mod)
sys.modules.setdefault("homeassistant.util.dt", homeassistant_dt_mod)

reporting_path = component_dir / "reporting.py"
reporting_spec = importlib.util.spec_from_file_location(
    "custom_components.astra_energy.reporting", reporting_path
)
assert reporting_spec and reporting_spec.loader
reporting = importlib.util.module_from_spec(reporting_spec)
sys.modules[reporting_spec.name] = reporting
reporting_spec.loader.exec_module(reporting)


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
        astra_api._session_id("user@example.test", "secret")
        == "063fe5677535abe6f556fbfdbd9a6978"
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
    assert readings[0].grid_kwh_total == 4695.978
    assert readings[0].solar_kwh_total == 743.183
    assert readings[0].total_kwh == 5517.247
    assert readings[0].raw["channels"]["grid"]["raw_meter_id"] == "ZT1_052_0"
    assert readings[0].raw["channels"]["solar"]["raw_meter_id"] == "ZT2_052_0"


def test_energy_balance_values_from_payload() -> None:
    values = astra_api._energy_balance_values_from_payload(
        {
            "auth": "1",
            "data": [
                {"v01": "Netzbezug", "v02": "402,801", "v03": "kWh"},
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


def test_reporting_error_payload() -> None:
    payload = reporting.error_payload(RuntimeError("boom"))
    assert payload["type"] == "RuntimeError"
    assert payload["message"] == "boom"
    assert "timestamp" in payload


def test_reporting_count_summary() -> None:
    assert reporting.summarize_counts({"b": 2, "a": 1}) == "a: 1, b: 2"
    assert reporting.summarize_counts({}) == "no readings"
