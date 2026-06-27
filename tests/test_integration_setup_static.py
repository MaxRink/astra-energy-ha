from __future__ import annotations

import ast
from pathlib import Path


def test_unload_callbacks_do_not_register_task_cancel_directly() -> None:
    """Task.cancel returns bool, which Home Assistant may try to schedule."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "__init__.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "async_on_unload":
            continue
        assert node.args, "async_on_unload callback is missing"
        callback = node.args[0]
        assert not (
            isinstance(callback, ast.Attribute) and callback.attr == "cancel"
        ), "Wrap Task.cancel so the unload callback returns None"


def test_import_statistics_registers_scheduled_backfill() -> None:
    """Configured historical imports must run without manual service calls."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert "async_track_time_interval" in source
    assert "CONF_IMPORT_STATISTICS" in source
    assert "_async_run_configured_backfill" in source
    assert "max(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL), 3600)" in source
    assert "await initial_refresh_task" in source
    assert "_cancel_initial_backfill" in source


def test_setup_normalizes_legacy_default_poll_interval() -> None:
    """Existing entries created with the old default should move to hourly polling."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert "_LEGACY_DEFAULT_POLL_INTERVAL = 900" in source
    assert "CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL" in source
    assert "_normalize_entry_options(hass, entry)" in source


def test_backfill_service_accepts_days_alias() -> None:
    """Manual recovery should accept the short alias used by operators."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert '_CONF_BACKFILL_DAYS_ALIASES = (CONF_BACKFILL_DAYS, "days")' in source
    assert 'vol.Optional("days")' in source
    assert "_service_value(" in source


def test_options_flow_auto_reloads_config_entry() -> None:
    """Options changes should not require a Home Assistant restart."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "config_flow.py"
    ).read_text(encoding="utf-8")

    assert "class AstraEnergyOptionsFlow(config_entries.OptionsFlowWithReload):" in source
    assert "data_schema=_options_schema(dict(self._config_entry.options))" in source
    assert "data_schema=_data_schema(dict(self._config_entry.options))" not in source
