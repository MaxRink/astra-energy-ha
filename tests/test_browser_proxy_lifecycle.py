from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_ensure_page_retries_after_stale_profile_locks(monkeypatch, tmp_path) -> None:
    for name in ("SingletonCookie", "SingletonLock", "SingletonSocket", "Default/LOCK"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    attempts = []

    class Context:
        pages = []

        def new_page(self):
            return object()

    def launch(profile, **options):
        attempts.append((profile, options))
        if len(attempts) == 1:
            raise RuntimeError("stale profile lock")
        return Context()

    monkeypatch.setitem(sys.modules, "cloakbrowser", SimpleNamespace(launch_persistent_context=launch))
    session = app.AstraBrowserSession(app.ProxyConfig(profile_dir=str(tmp_path)))

    session._ensure_page()

    assert len(attempts) == 2
    assert not any((tmp_path / name).exists() for name in ("SingletonCookie", "SingletonLock", "SingletonSocket", "Default/LOCK"))


def test_ensure_page_recreates_closed_browser_context(monkeypatch) -> None:
    class ClosedContext:
        @property
        def pages(self):
            raise RuntimeError("closed context")

        def close(self):
            return None

    class FreshContext:
        pages = []

        def cookies(self, *args):
            return []

        def new_page(self):
            return object()

    launches = []

    def launch(profile, **options):
        launches.append(profile)
        return FreshContext()

    monkeypatch.setitem(sys.modules, "cloakbrowser", SimpleNamespace(launch_persistent_context=launch))
    session = app.AstraBrowserSession(app.ProxyConfig())
    session._context = ClosedContext()
    session._page = object()

    session._ensure_page()

    assert launches == [session.config.profile_dir]
    assert session._context.__class__ is FreshContext


def test_capture_session_recovers_once_from_closed_context(monkeypatch) -> None:
    class ClosedContext:
        def cookies(self, *args):
            raise RuntimeError("closed context")

        def close(self):
            return None

    class FreshContext:
        pages = []

        def cookies(self, *args):
            return []

        def new_page(self):
            return object()

    launches = []

    def launch(profile, **options):
        launches.append(profile)
        return FreshContext()

    monkeypatch.setitem(sys.modules, "cloakbrowser", SimpleNamespace(launch_persistent_context=launch))
    session = app.AstraBrowserSession(app.ProxyConfig())
    session._context = ClosedContext()
    session._page = object()
    session._last_cookie = "restored-cookie"
    session._last_session_id = "restored-session"
    session._fetch_meter_widget = lambda *args: "Strom VGB 1,00 kWh"  # type: ignore[method-assign]
    monkeypatch.setattr(app, "parse_meter_widget", lambda html, fallback_meter_id: {"meter_id": fallback_meter_id})

    result = session.current()

    assert result["ok"] is True
    assert launches == [session.config.profile_dir]


def test_current_reports_safe_fetch_phase_for_unexpected_provider_error() -> None:
    session = app.AstraBrowserSession(app.ProxyConfig())
    session._last_cookie = "cookie"
    session._last_session_id = "session"
    session._ensure_page = lambda: None  # type: ignore[method-assign]
    session._capture_browser_session = lambda: None  # type: ignore[method-assign]

    def broken_fetch(*args):
        raise RuntimeError("provider response must not escape")

    session._fetch_meter_widget = broken_fetch  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="provider response must not escape"):
        session.current()
    assert session._current_phase == "fetch_widget"


def test_request_text_classifies_fake_http_failure_without_body() -> None:
    class BrokenOpener:
        def open(self, request, timeout):
            raise app.HTTPError(request.full_url, 502, "bad gateway", {}, None)

    with pytest.raises(app.AstraWebError, match="web returned HTTP 502"):
        app.AstraBrowserSession(app.ProxyConfig())._request_text(
            BrokenOpener(),
            "https://provider.invalid/widget",
            data=None,
            headers={},
            timeout_seconds=10,
        )


def test_fetch_widget_follows_dashboard_widget_route(monkeypatch) -> None:
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body.encode()
            self.status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.body

    class FakeOpener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.method))
            if request.full_url.endswith("/pm_customlogin.php"):
                return Response('<iframe src="wg_replastzs.php?sessionId=session"></iframe>')
            return Response("Strom VGB 1,00 kWh")

    monkeypatch.setattr(app, "build_opener", lambda *args: FakeOpener())
    session = app.AstraBrowserSession(app.ProxyConfig(web_base_url="https://provider.invalid/base"))
    html = session._fetch_meter_widget("session", "cookie=value")

    assert html == "Strom VGB 1,00 kWh"
    assert calls == [
        ("https://provider.invalid/base/pm_customlogin.php", "POST"),
        ("https://provider.invalid/base/wg_replastzs.php?sessionId=session", "GET"),
    ]
