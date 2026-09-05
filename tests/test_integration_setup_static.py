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

    assert 'vol.Optional("days")' in source
    assert "days = call.data.get(" in source
    assert "CONF_BACKFILL_DAYS" in source
    assert "_service_value(" not in source
    assert "_async_background_backfill" not in source
    assert "hass.async_create_task(_async_backfill_history(hass, call))" in source


def test_config_flow_shares_option_schema_and_validates_with_login() -> None:
    """Data and options flows must keep one set of option validators."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "config_flow.py"
    ).read_text(encoding="utf-8")

    assert "def _options_schema_fields(" in source
    assert "fields.update(_options_schema_fields(defaults))" in source
    assert "vol.Schema(_options_schema_fields(defaults or {}))" in source
    assert "step=" not in source
    assert "unit=" not in source
    assert "await client.async_login()" in source
    assert "async_get_account_info" not in source


def test_unused_auth_surfaces_are_removed() -> None:
    """Keep the API surface limited to paths used by the integration."""
    api_source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "api.py"
    ).read_text(encoding="utf-8")
    web_source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "web_session.py"
    ).read_text(encoding="utf-8")

    for name in (
        "AstraAccountInfo",
        "AstraApiNotDocumentedError",
        "_last_login_payload",
        "async_get_account_info",
        "self._base_url =",
        "def _post_raw(",
    ):
        assert name not in api_source
    assert "def as_dict(" not in web_source
    assert "AstraWebSessionError" not in web_source


def test_options_flow_auto_reloads_config_entry() -> None:
    """Options changes should not require a Home Assistant restart."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "config_flow.py"
    ).read_text(encoding="utf-8")

    assert "class AstraEnergyOptionsFlow(config_entries.OptionsFlowWithReload):" in source
    assert "data_schema=_options_schema(dict(self._config_entry.options))" in source
    assert "data_schema=_data_schema(dict(self._config_entry.options))" not in source


def test_setup_treats_missing_stored_credentials_as_reauth() -> None:
    """Stale entries must not fail with a KeyError or start an anonymous client."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert 'entry.data.get(CONF_USERNAME)' in source
    assert 'entry.data.get(CONF_PASSWORD)' in source
    assert "ConfigEntryAuthFailed(" in source
    assert "reauthenticate the integration" in source
    assert "async_start_reauth" in source


def test_background_auth_failure_starts_reauth_without_reraising() -> None:
    """Detached refresh tasks must start HA reauth themselves."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "__init__.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_async_background_initial_refresh"
    )
    handler = next(
        handler
        for node in ast.walk(function)
        if isinstance(node, ast.Try)
        for handler in node.handlers
        if isinstance(handler.type, ast.Name)
        and handler.type.id == "ConfigEntryAuthFailed"
    )

    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "async_start_reauth"
        for node in ast.walk(handler)
    )
    assert not any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def test_reauth_updates_existing_entry_and_handles_removed_entry() -> None:
    """Reauth must target the original entry, including after stale flow context."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "config_flow.py"
    ).read_text(encoding="utf-8")

    assert 'self.context.get("entry_id")' in source
    assert 'self.async_abort(reason="entry_not_found")' in source
    assert "self.async_update_reload_and_abort(entry, data_updates=merged)" in source
