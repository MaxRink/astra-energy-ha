"""Local Astra web browser proxy sidecar."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic, perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

ASTRA_TZ = ZoneInfo("Europe/Berlin")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("astra-browser-proxy")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ProxyConfig:
    bind: str = os.getenv("ASTRA_BIND", "127.0.0.1")
    port: int = int(os.getenv("ASTRA_PORT", "43104"))
    profile_dir: str = os.getenv("ASTRA_PROFILE_DIR", "/profile")
    headless: bool = _env_bool("ASTRA_HEADLESS", False)
    web_base_url: str = os.getenv(
        "ASTRA_WEB_BASE_URL",
        "https://astra-cloud.com/astra04/readyxnet/source/pm",
    ).rstrip("/")
    login_url: str = os.getenv(
        "ASTRA_LOGIN_URL",
        "https://astra-cloud.com/readyxnet/source/login/csloginw.php",
    )
    username: str = os.getenv("ASTRA_USERNAME", "")
    password: str = os.getenv("ASTRA_PASSWORD", "")
    shared_token: str = os.getenv("ASTRA_SHARED_TOKEN", "")
    meter_id: str = os.getenv("ASTRA_METER_ID", "astra_meter")
    initial_session_id: str = os.getenv("ASTRA_SESSION_ID", "")
    initial_cookie: str = os.getenv("ASTRA_COOKIE", "")
    dashboard_timeout_seconds: int = min(
        max(int(os.getenv("ASTRA_DASHBOARD_TIMEOUT_SECONDS", "10")), 5), 30
    )
    widget_timeout_seconds: int = min(
        max(int(os.getenv("ASTRA_WIDGET_TIMEOUT_SECONDS", "55")), 10), 60
    )
    current_cache_seconds: int = min(
        max(int(os.getenv("ASTRA_CURRENT_CACHE_SECONDS", "30")), 0), 300
    )
    session_refresh_seconds: int = min(
        max(int(os.getenv("ASTRA_SESSION_REFRESH_SECONDS", "3600")), 30), 3600
    )


class AstraWebError(RuntimeError):
    """Astra web frontend could not provide usable data."""


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AstraWebError("Astra web URL has an invalid origin")
    if parsed.username or parsed.password:
        raise AstraWebError("Astra web URL must not contain credentials")
    scheme = parsed.scheme.lower()
    port = parsed.port
    if port is None and scheme == "https":
        port = 443
    elif port is None and scheme == "http":
        port = 80
    return scheme, parsed.hostname.lower(), port


def _same_origin(url: str, expected: tuple[str, str, int | None]) -> bool:
    try:
        return _origin(url) == expected
    except (AstraWebError, ValueError):
        return False


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def __init__(self, expected_origin: tuple[str, str, int | None]) -> None:
        super().__init__()
        self._expected_origin = expected_origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _same_origin(newurl, self._expected_origin):
            raise AstraWebError("Astra web redirect crossed the configured origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class AstraBrowserSession:
    """Persistent browser profile and web-widget fetcher."""

    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._context = None
        self._page = None
        self._last_session_id = config.initial_session_id
        self._last_cookie = config.initial_cookie
        self._last_login_attempt: str | None = None
        self._last_current: dict[str, Any] | None = None
        self._last_current_at = 0.0
        self._current_phase = "idle"
        self._last_session_capture_at = 0.0

    def health(self) -> dict[str, Any]:
        with self._lock:
            context_healthy: bool | None = None
            if self._context is not None:
                try:
                    self._context.pages
                    context_healthy = True
                except Exception:  # noqa: BLE001
                    context_healthy = False
            return {
                "ok": True,
                "browser_started": self._context is not None,
                "browser_context_healthy": context_healthy,
                "has_cookie": bool(self._last_cookie),
                "has_session_id": bool(self._last_session_id),
                "last_login_attempt": self._last_login_attempt,
                "profile_dir": self.config.profile_dir,
            }

    def login(self) -> dict[str, Any]:
        with self._lock:
            page = self._ensure_page()
            navigation_started = perf_counter()
            try:
                page.goto(self.config.login_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as err:  # noqa: BLE001
                LOGGER.warning(
                    "phase=browser_navigation_failed error_type=%s elapsed_ms=%.1f",
                    type(err).__name__,
                    (perf_counter() - navigation_started) * 1000,
                )
                raise AstraWebError(
                    f"Astra browser navigation failed: {type(err).__name__}"
                ) from err
            LOGGER.info("phase=browser_navigation_done elapsed_ms=%.1f", (perf_counter() - navigation_started) * 1000)
            self._last_login_attempt = datetime.now(ASTRA_TZ).isoformat()
            login_origin = _origin(self.config.login_url)
            if not _same_origin(page.url, login_origin):
                LOGGER.warning("Astra login navigation crossed the configured origin; autofill skipped")
            elif self.config.username and self.config.password:
                self._fill_best_effort_login(page)
            self._capture_browser_session()
            self._last_session_capture_at = monotonic()
            return {
                "ok": True,
                "url": _redact_url(page.url),
                "title": page.title(),
                "has_cookie": bool(self._last_cookie),
                "has_session_id": bool(self._last_session_id),
                "note": "Complete interactive login through CDP if Astra shows a challenge.",
            }

    def current(self) -> dict[str, Any]:
        started = perf_counter()
        with self._lock:
            self._current_phase = "cache_check"
            if self._last_current is not None and (
                monotonic() - self._last_current_at < self.config.current_cache_seconds
            ):
                LOGGER.info("phase=current_cache_hit age_ms=%.1f", (monotonic() - self._last_current_at) * 1000)
                return json.loads(json.dumps(self._last_current))
            capture_started = perf_counter()
            self._current_phase = "capture_session"
            should_capture = (
                not self._last_cookie
                or not self._last_session_id
                or monotonic() - self._last_session_capture_at
                >= self.config.session_refresh_seconds
            )
            if should_capture:
                try:
                    # The widget request uses the last validated cookie and
                    # session ID directly.  Do not touch the persistent
                    # browser context on every poll: its Playwright cookie
                    # transport can become stale while the provider session
                    # remains valid.  Reattach only when metadata is absent
                    # or the bounded refresh interval has elapsed.
                    self._current_phase = "ensure_page"
                    self._ensure_page()
                    self._capture_browser_session()
                    self._last_session_capture_at = monotonic()
                except AstraWebError as err:
                    # A crashed browser context can retain truthy cookie/session
                    # metadata while every Playwright operation fails. Recreate
                    # it once so a normal refresh can recover without exposing
                    # provider credentials or hammering the login endpoint.
                    LOGGER.warning(
                        "phase=capture_session_recover error_type=%s",
                        type(err).__name__,
                    )
                    self._ensure_page()
                    self._capture_browser_session()
                    self._last_session_capture_at = monotonic()
            else:
                LOGGER.info(
                    "phase=capture_session_skipped age_s=%.1f",
                    monotonic() - self._last_session_capture_at,
                )
            LOGGER.info("phase=capture_session elapsed_ms=%.1f has_cookie=%s has_session_id=%s", (perf_counter() - capture_started) * 1000, bool(self._last_cookie), bool(self._last_session_id))
            if not self._last_cookie or not self._last_session_id:
                LOGGER.info("phase=login_start")
                self._current_phase = "login"
                login_started = perf_counter()
                self.login()
                LOGGER.info("phase=login_done elapsed_ms=%.1f has_cookie=%s has_session_id=%s", (perf_counter() - login_started) * 1000, bool(self._last_cookie), bool(self._last_session_id))
                self._capture_browser_session()
            if not self._last_cookie or not self._last_session_id:
                raise AstraWebError(
                    "No logged-in Astra browser session is available; complete login through CDP"
                )

            fetch_started = perf_counter()
            self._current_phase = "fetch_widget"
            html = self._fetch_meter_widget(self._last_session_id, self._last_cookie)
            LOGGER.info("phase=widget_fetch_done elapsed_ms=%.1f response_bytes=%s", (perf_counter() - fetch_started) * 1000, len(html.encode("latin-1", errors="ignore")))
            parse_started = perf_counter()
            self._current_phase = "parse_widget"
            meter = parse_meter_widget(
                html,
                fallback_meter_id=self.config.meter_id,
            )
            LOGGER.info(
                "phase=parse_done elapsed_ms=%.1f total_elapsed_ms=%.1f",
                (perf_counter() - parse_started) * 1000,
                (perf_counter() - started) * 1000,
            )
            result = {
                "ok": True,
                "source": "astra_web_widget",
                "fetched_at": datetime.now(ASTRA_TZ).isoformat(),
                "meter": meter,
            }
            # Only successful parsed responses are cached. A failed or empty
            # response cannot overwrite a known-good result or extend its age.
            self._last_current = result
            self._last_current_at = monotonic()
            self._current_phase = "complete"
            return json.loads(json.dumps(result))

    def history(self, day: str) -> dict[str, Any]:
        """Read one provider day as timestamped graph intervals.

        This is deliberately a bounded, read-only operation.  It uses the
        already authenticated browser session and never writes HA history.
        """
        try:
            start = date.fromisoformat(day)
        except ValueError as err:
            raise AstraWebError("history date must be YYYY-MM-DD") from err
        if start < date(2020, 1, 1) or start > date.today() + timedelta(days=1):
            raise AstraWebError("history date is outside the supported range")
        with self._lock:
            self.current()
            headers = {
                "User-Agent": "Mozilla/5.0 AstraEnergyBrowserProxy/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Cookie": self._last_cookie,
            }
            opener = build_opener(_SameOriginRedirectHandler(_origin(self.config.web_base_url)))
            dashboard = self._request_text(
                opener,
                f"{self.config.web_base_url}/pm_customlogin.php",
                data={"sessionId": self._last_session_id, "s_stat": "1", "s_ver": "3"},
                headers=headers,
                timeout_seconds=self.config.dashboard_timeout_seconds,
            )
            route = re.search(r"(?:[\"'])([^\"']*pm_graph\.php[^\"']*)(?:[\"'])", dashboard)
            params = {
                "sessionId": self._last_session_id,
                "s_vom": start.strftime("%d.%m.%Y"),
                "s_bis": (start + timedelta(days=1)).strftime("%d.%m.%Y"),
                "s_tvom": start.strftime("%Y-%m-%d 00:00:00"),
                "s_tbis": (start + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"),
            }
            if route:
                observed = parse_qs(urlparse(unescape(route.group(1))).query)
                params.update({key: values[0] for key, values in observed.items() if values})
                params["sessionId"] = self._last_session_id
                params["s_vom"] = start.strftime("%d.%m.%Y")
                params["s_bis"] = (start + timedelta(days=1)).strftime("%d.%m.%Y")
                params["s_tvom"] = start.strftime("%Y-%m-%d 00:00:00")
                params["s_tbis"] = (start + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
                graph_path = urljoin(f"{self.config.web_base_url}/", unescape(route.group(1))).split("?", 1)[0]
            else:
                graph_path = f"{self.config.web_base_url}/pm_graph.php"
            url = f"{graph_path}?{urlencode(params)}"
            html = self._request_text(
                opener,
                url,
                data=None,
                headers=headers,
                timeout_seconds=60,
            )
            points = _parse_graph_points(html)
            if not points:
                raise AstraWebError("Astra history graph contained no timestamped intervals")
            return {"ok": True, "source": "astra_web_graph", "date": day, "points": points}

    def _ensure_page(self):
        if self._context is not None:
            try:
                pages = self._context.pages
            except Exception as err:  # noqa: BLE001
                LOGGER.warning(
                    "phase=browser_context_stale error_type=%s",
                    type(err).__name__,
                )
                self._invalidate_context()
            else:
                if self._page is not None and getattr(self._page, "is_closed", lambda: False)():
                    self._page = None
                if self._page is None:
                    self._page = pages[0] if pages else self._context.new_page()
                return self._page
        if self._context is None:
            try:
                from cloakbrowser import launch_persistent_context
            except ImportError as err:
                raise AstraWebError("CloakBrowser is not installed in the sidecar") from err
            os.makedirs(self.config.profile_dir, exist_ok=True)
            options = dict(
                headless=self.config.headless,
                locale="de-DE",
                timezone="Europe/Berlin",
                args=[
                    "--remote-debugging-port=9222",
                    "--remote-debugging-address=127.0.0.1",
                    "--disable-http2",
                ],
            )
            try:
                self._context = launch_persistent_context(self.config.profile_dir, **options)
            except Exception as err:  # noqa: BLE001
                self._clear_stale_profile_locks()
                LOGGER.warning("Astra browser launch retry: %s", type(err).__name__)
                try:
                    self._context = launch_persistent_context(self.config.profile_dir, **options)
                except Exception as retry_err:  # noqa: BLE001
                    raise AstraWebError(
                        f"Astra browser launch failed: {type(retry_err).__name__}"
                    ) from retry_err
        pages = self._context.pages
        if self._page is None:
            self._page = pages[0] if pages else self._context.new_page()
        return self._page

    def _invalidate_context(self) -> None:
        context = self._context
        self._context = None
        self._page = None
        if context is not None:
            try:
                context.close()
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("Could not close stale Astra browser context: %s", type(err).__name__)

    def _clear_stale_profile_locks(self) -> None:
        for name in ("SingletonCookie", "SingletonLock", "SingletonSocket", "Default/LOCK"):
            path = os.path.join(self.config.profile_dir, name)
            try:
                os.unlink(path)
            except FileNotFoundError:
                continue
            except OSError as err:
                LOGGER.warning("Could not clear Astra profile lock: %s", type(err).__name__)

    def _fill_best_effort_login(self, page) -> None:
        selectors = (
            ("input[name='username']", self.config.username),
            ("input[name='user']", self.config.username),
            ("input[name='login']", self.config.username),
            ("input[type='text']", self.config.username),
            ("input[name='password']", self.config.password),
            ("input[name='pass']", self.config.password),
            ("input[type='password']", self.config.password),
        )
        for selector, value in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count():
                    locator.fill(value, timeout=2000)
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("Could not fill login selector %s: %s", selector, type(err).__name__)
                continue
        for selector in (
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Anmelden')",
        ):
            try:
                locator = page.locator(selector).first
                if locator.count():
                    locator.click(timeout=2000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    return
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("Could not click login selector %s: %s", selector, type(err).__name__)
                continue

    def _capture_browser_session(self) -> None:
        if self._context is None:
            return
        expected_origin = _origin(self.config.web_base_url)
        try:
            try:
                cookies = self._context.cookies([self.config.web_base_url])
            except TypeError:
                # Older Playwright/CloakBrowser builds do not accept an
                # origin argument. Keep the fallback inside the same
                # recovery boundary because a closed context can fail both
                # calls with different exception types.
                cookies = self._context.cookies()
        except Exception as err:  # noqa: BLE001
            self._invalidate_context()
            raise AstraWebError("Astra browser context is unavailable") from err
        cookies = [
            cookie
            for cookie in cookies
            if _cookie_matches_origin(cookie, expected_origin)
        ]
        if cookies:
            self._last_cookie = "; ".join(
                f"{cookie['name']}={cookie['value']}" for cookie in cookies
            )
        for page in self._context.pages:
            if not _same_origin(page.url, expected_origin):
                continue
            parsed = urlparse(page.url)
            session_id = parse_qs(parsed.query).get("sessionId", [""])[0]
            if session_id:
                self._last_session_id = session_id
                return

    def _fetch_meter_widget(self, session_id: str, cookie: str) -> str:
        expected_origin = _origin(self.config.web_base_url)
        opener = build_opener(_SameOriginRedirectHandler(expected_origin))
        headers = {
            "User-Agent": "Mozilla/5.0 AstraEnergyBrowserProxy/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cookie": cookie,
        }
        dashboard = self._request_text(
            opener,
            f"{self.config.web_base_url}/pm_customlogin.php",
            data={
                "sessionId": session_id,
                "s_stat": "1",
                "s_ver": "3",
            },
            headers=headers,
            timeout_seconds=self.config.dashboard_timeout_seconds,
        )
        widget_url = _find_widget_url(dashboard, self.config.web_base_url, session_id)
        return self._request_text(
            opener,
            widget_url,
            data=None,
            headers=headers,
            timeout_seconds=self.config.widget_timeout_seconds,
        )

    def _request_text(
        self,
        opener,
        url: str,
        *,
        data: dict[str, str] | None,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> str:
        body = urlencode(data).encode() if data is not None else None
        request = Request(url, data=body, headers=headers, method="POST" if body else "GET")
        request_started = perf_counter()
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                raw = response.read()
                LOGGER.info("phase=http_fetch_done status=%s elapsed_ms=%.1f response_bytes=%s", response.status, (perf_counter() - request_started) * 1000, len(raw))
        except HTTPError as err:
            LOGGER.warning("phase=http_fetch_failed status=%s elapsed_ms=%.1f", err.code, (perf_counter() - request_started) * 1000)
            raise AstraWebError(f"Astra web returned HTTP {err.code}") from err
        except URLError as err:
            LOGGER.warning("phase=http_fetch_failed error=%s elapsed_ms=%.1f", type(err.reason).__name__, (perf_counter() - request_started) * 1000)
            raise AstraWebError("Astra web request failed") from err
        except TimeoutError as err:
            LOGGER.warning("phase=http_fetch_failed error=TimeoutError elapsed_ms=%.1f", (perf_counter() - request_started) * 1000)
            raise AstraWebError("Astra web request timed out") from err
        text = raw.decode("latin-1", errors="ignore")
        lowered = text.casefold()
        if "recaptcha" in lowered or "g-recaptcha" in lowered:
            raise AstraWebError("Astra returned a reCAPTCHA login page")
        if (
            ("cslogin" in lowered and "passwort" in lowered)
            or ("<form" in lowered and "password" in lowered and "login" in lowered)
        ):
            raise AstraWebError("Astra browser session is logged out")
        if not text.strip():
            raise AstraWebError("Astra web returned an empty response")
        return text


def _find_widget_url(dashboard_html: str, base_url: str, session_id: str) -> str:
    match = re.search(r"""["']([^"']*wg_replastzs\.php[^"']*)["']""", dashboard_html)
    if match:
        widget_url = urljoin(f"{base_url}/", unescape(match.group(1)))
        if not _same_origin(widget_url, _origin(base_url)):
            raise AstraWebError("Astra widget URL crossed the configured origin")
        return widget_url
    return f"{base_url}/wg_replastzs.php?{urlencode({'sessionId': session_id})}"


_GRAPH_TITLE_RE = re.compile(
    r'TITLE="[^"]* ist\s+([0-9.,-]+)\s+kWh\s+um\s+'
    r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)


def _parse_graph_points(html: str) -> list[dict[str, Any]]:
    """Parse graph image-map markers into timestamped cumulative/interval data."""
    values: dict[datetime, list[float]] = {}
    for raw_value, raw_timestamp in _GRAPH_TITLE_RE.findall(html):
        timestamp = datetime.strptime(raw_timestamp, "%d.%m.%Y %H:%M:%S").replace(tzinfo=ASTRA_TZ)
        value = _parse_german_number(raw_value)
        values.setdefault(timestamp, []).append(value)
    points = []
    for timestamp, readings in sorted(values.items()):
        positive = [value for value in readings if value >= 0]
        if positive:
            points.append({
                "timestamp": timestamp.isoformat(),
                "cumulative_kwh": max(positive),
                "interval_kwh": min(positive),
            })
    return points


def _cookie_matches_origin(cookie: dict[str, Any], expected: tuple[str, str, int | None]) -> bool:
    domain = str(cookie.get("domain") or "").lstrip(".").lower()
    return bool(domain) and domain == expected[1]


def parse_meter_widget(html: str, *, fallback_meter_id: str) -> dict[str, Any]:
    """Parse the current meter-stand widget into redaction-safe JSON."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</(?:tr|div|p|li|table)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", unescape(text))
    text = re.sub(r"\n\s+", "\n", text).strip()
    rows = {
        "total": _find_row(text, r"Strom\s+VGB"),
        "grid": _find_row(text, r"Strom\s+T1"),
        "solar": _find_row(text, r"Strom\s+T2"),
    }
    parsed = {key: _parse_row(row) for key, row in rows.items() if row}
    total = parsed.get("total", {})
    grid = parsed.get("grid", {})
    solar = parsed.get("solar", {})
    total_stand = total.get("stand_kwh")
    solar_stand = solar.get("stand_kwh")
    raw_grid_stand = grid.get("stand_kwh")
    grid_stand = (
        max(total_stand - solar_stand, 0.0)
        if total_stand is not None and solar_stand is not None
        else raw_grid_stand
    )
    if total_stand is None and grid_stand is not None and solar_stand is not None:
        total_stand = grid_stand + solar_stand
    if total_stand is None and grid_stand is None and solar_stand is None:
        raise AstraWebError("Astra meter widget contained no usable kWh values")

    raw_meter_id = total.get("meter_id") or fallback_meter_id
    timestamp = total.get("timestamp") or grid.get("timestamp") or solar.get("timestamp")
    return {
        "meter_id": _stable_meter_id(raw_meter_id),
        "meter_name": "Astra Energy Meter",
        "raw_meter_id": raw_meter_id,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "total_kwh": total_stand,
        "grid_kwh": grid_stand,
        "raw_grid_kwh": raw_grid_stand,
        "solar_kwh": solar_stand,
        "current_year_total_kwh": total.get("period_kwh"),
        "current_year_grid_kwh": grid.get("period_kwh"),
        "current_year_raw_grid_kwh": grid.get("period_kwh"),
        "current_year_solar_kwh": solar.get("period_kwh"),
    }


def _find_row(text: str, label_re: str) -> str | None:
    match = re.search(
        rf"({label_re}.*?)(?=\n?\s*Strom\s+(?:VGB|T1|T2)|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else None


def _parse_row(row: str) -> dict[str, Any]:
    values = [_parse_german_number(value) for value in re.findall(r"([0-9.]+,[0-9]+)\s*kWh", row)]
    dates = re.findall(r"\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?", row)
    meter_ids = re.findall(r"\b([A-Z0-9]{3,}[A-Z0-9_]*\/0)\b", row)
    return {
        "stand_kwh": values[0] if values else None,
        "period_kwh": values[-1] if len(values) >= 2 else None,
        "timestamp": _parse_german_timestamp(dates[0]) if dates else None,
        "meter_id": meter_ids[0] if meter_ids else None,
    }


def _parse_german_number(value: str) -> float:
    return round(float(value.replace(".", "").replace(",", ".")), 6)


def _parse_german_timestamp(value: str) -> datetime:
    fmt = "%d.%m.%Y %H:%M" if " " in value else "%d.%m.%Y"
    return datetime.strptime(value, fmt).replace(tzinfo=ASTRA_TZ)


def _stable_meter_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_") or "astra_meter"


def _redact_url(value: str) -> str:
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    if "sessionId" in query:
        query["sessionId"] = ["<redacted>"]
    return parsed._replace(query=urlencode(query, doseq=True)).geturl()


CONFIG = ProxyConfig()
SESSION = AstraBrowserSession(CONFIG)


class Handler(BaseHTTPRequestHandler):
    server_version = "AstraBrowserProxy/1.0"

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, SESSION.health())
            return
        if self.path == "/current":
            self._handle_current()
            return
        if self.path.startswith("/history"):
            self._handle_history()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if self.path == "/login":
            try:
                self._send_json(HTTPStatus.OK, SESSION.login())
            except AstraWebError as err:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(err)})
            except Exception as err:  # noqa: BLE001
                LOGGER.warning("Astra login request failed: %s", type(err).__name__)
                self._send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": f"Astra browser login failed: {type(err).__name__}"},
                )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def _handle_current(self) -> None:
        try:
            self._send_json(HTTPStatus.OK, SESSION.current())
        except AstraWebError as err:
            LOGGER.warning("Current fetch failed: %s", type(err).__name__)
            self._send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(err)})
        except Exception as err:  # noqa: BLE001
            phase = getattr(SESSION, "_current_phase", "unknown")
            LOGGER.warning("Astra current request failed: phase=%s error_type=%s", phase, type(err).__name__)
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"ok": False, "error": f"Astra current request failed: phase={phase} error_type={type(err).__name__}"},
            )

    def _handle_history(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        day = (query.get("date") or [""])[0]
        try:
            self._send_json(HTTPStatus.OK, SESSION.history(day))
        except AstraWebError as err:
            LOGGER.warning("History fetch failed: %s", type(err).__name__)
            self._send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(err)})
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("Astra history request failed: error_type=%s", type(err).__name__)
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"ok": False, "error": f"Astra history request failed: {type(err).__name__}"},
            )

    def _authorized(self) -> bool:
        if not CONFIG.shared_token:
            return True
        return self.headers.get("Authorization") == f"Bearer {CONFIG.shared_token}"

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.debug(format, *args)


def main() -> None:
    if CONFIG.bind != "127.0.0.1" and not CONFIG.shared_token:
        raise RuntimeError("Refusing to start unauthenticated proxy on non-loopback address. Set ASTRA_SHARED_TOKEN or bind to 127.0.0.1.")
    server = ThreadingHTTPServer((CONFIG.bind, CONFIG.port), Handler)
    LOGGER.info("Starting Astra browser proxy on %s:%s", CONFIG.bind, CONFIG.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
