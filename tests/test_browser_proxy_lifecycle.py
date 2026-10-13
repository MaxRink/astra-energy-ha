from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


APP_PATH = Path(__file__).parents[1] / "tools" / "astra_browser_proxy" / "app.py"
SPEC = importlib.util.spec_from_file_location("astra_browser_proxy_app", APP_PATH)
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


def test_login_converts_navigation_failure_to_safe_proxy_error() -> None:
    session = app.AstraBrowserSession(app.ProxyConfig())

    class BrokenPage:
        def goto(self, *args, **kwargs):
            raise TimeoutError("provider details must not escape")

    session._ensure_page = lambda: BrokenPage()  # type: ignore[method-assign]

    with pytest.raises(app.AstraWebError, match="navigation failed: TimeoutError"):
        session.login()


def test_current_starts_browser_before_using_restored_session(monkeypatch) -> None:
    session = app.AstraBrowserSession(app.ProxyConfig())
    events: list[str] = []
    session._last_cookie = "restored-cookie"
    session._last_session_id = "restored-session"
    session._ensure_page = lambda: events.append("ensure")  # type: ignore[method-assign]
    session._capture_browser_session = lambda: events.append("capture")  # type: ignore[method-assign]
    session._fetch_meter_widget = lambda *args: "unused"  # type: ignore[method-assign]
    monkeypatch.setattr(
        app,
        "parse_meter_widget",
        lambda html, fallback_meter_id: {"meter_id": fallback_meter_id},
    )

    result = session.current()

    assert result["ok"] is True
    assert events[:2] == ["ensure", "capture"]
