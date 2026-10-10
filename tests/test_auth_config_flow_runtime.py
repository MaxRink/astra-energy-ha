from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest


class _VolKey:
    def __init__(self, key, default=None) -> None:
        self.key = key
        self.default = default

    def __hash__(self) -> int:
        return hash((self.key, self.default))


class _ConfigFlowStub:
    def __init_subclass__(cls, **_kwargs) -> None:
        return super().__init_subclass__()

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}


class _OptionsFlowStub:
    pass


def _load_config_flow(monkeypatch):
    """Load config_flow with test-only modules restored by pytest afterwards."""
    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Required = _VolKey
    voluptuous.Optional = _VolKey
    voluptuous.Schema = lambda schema: schema
    voluptuous.All = lambda *validators: validators
    voluptuous.Coerce = lambda converter: converter
    voluptuous.Range = lambda **kwargs: kwargs
    voluptuous.In = lambda values: values
    monkeypatch.setitem(sys.modules, "voluptuous", voluptuous)

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigFlow = _ConfigFlowStub
    config_entries.OptionsFlowWithReload = _OptionsFlowStub
    homeassistant_const = types.ModuleType("homeassistant.const")
    homeassistant_const.CONF_PASSWORD = "password"
    homeassistant_const.CONF_USERNAME = "username"
    homeassistant_core = types.ModuleType("homeassistant.core")
    homeassistant_core.callback = lambda function: function
    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda _hass: None
    helpers.aiohttp_client = aiohttp_client
    homeassistant.config_entries = config_entries
    homeassistant.const = homeassistant_const
    homeassistant.core = homeassistant_core
    homeassistant.helpers = helpers
    for name, module in {
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
        "homeassistant.const": homeassistant_const,
        "homeassistant.core": homeassistant_core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    root = Path(__file__).parents[1]
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(root / "custom_components")]
    package = types.ModuleType("custom_components.astra_energy")
    package.__path__ = [str(root / "custom_components" / "astra_energy")]
    custom_components.astra_energy = package
    monkeypatch.setitem(sys.modules, "custom_components", custom_components)
    monkeypatch.setitem(sys.modules, "custom_components.astra_energy", package)

    for module_name in ("const", "api"):
        qualified = f"custom_components.astra_energy.{module_name}"
        path = root / "custom_components" / "astra_energy" / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(qualified, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, qualified, module)
        spec.loader.exec_module(module)

    qualified = "custom_components.astra_energy.config_flow"
    spec = importlib.util.spec_from_file_location(
        qualified, root / "custom_components" / "astra_energy" / "config_flow.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, qualified, module)
    spec.loader.exec_module(module)
    return module


class _Entry:
    def __init__(self, data: dict[str, str]) -> None:
        self.data = data


class _Entries:
    def __init__(self, entry: _Entry) -> None:
        self.entry = entry

    def async_get_entry(self, _entry_id):
        return self.entry


class _Hass:
    def __init__(self, entry: _Entry) -> None:
        self.config_entries = _Entries(entry)


@pytest.mark.parametrize(
    "entry_data",
    [
        {"password": "stored-password"},
        {"username": "stored-user"},
    ],
    ids=("missing-username", "missing-password"),
)
def test_reauth_ignores_ha_entry_data_when_showing_form(
    entry_data: dict[str, str], monkeypatch
) -> None:
    config_flow = _load_config_flow(monkeypatch)
    entry = _Entry(entry_data)
    flow = config_flow.AstraEnergyConfigFlow()
    flow.context = {"entry_id": "entry"}
    flow.hass = _Hass(entry)

    result = asyncio.run(flow.async_step_reauth(entry_data))

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
