"""Local Astra web browser proxy sidecar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import re
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, build_opener
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


class AstraWebError(RuntimeError):
    """Astra web frontend could not provide usable data."""


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

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "browser_started": self._context is not None,
                "has_cookie": bool(self._last_cookie),
                "has_session_id": bool(self._last_session_id),
                "last_login_attempt": self._last_login_attempt,
                "profile_dir": self.config.profile_dir,
            }

    def login(self) -> dict[str, Any]:
        with self._lock:
            page = self._ensure_page()
            page.goto(self.config.login_url, wait_until="domcontentloaded", timeout=30000)
            self._last_login_attempt = datetime.now(ASTRA_TZ).isoformat()
            if self.config.username and self.config.password:
                self._fill_best_effort_login(page)
            self._capture_browser_session()
            return {
                "ok": True,
                "url": _redact_url(page.url),
                "title": page.title(),
                "has_cookie": bool(self._last_cookie),
                "has_session_id": bool(self._last_session_id),
                "note": "Complete interactive login through CDP if Astra shows a challenge.",
            }

    def current(self) -> dict[str, Any]:
        with self._lock:
            self._capture_browser_session()
            if not self._last_cookie or not self._last_session_id:
                self.login()
                self._capture_browser_session()
            if not self._last_cookie or not self._last_session_id:
                raise AstraWebError(
                    "No logged-in Astra browser session is available; complete login through CDP"
                )

            html = self._fetch_meter_widget(self._last_session_id, self._last_cookie)
            meter = parse_meter_widget(
                html,
                fallback_meter_id=self.config.meter_id,
            )
            return {
                "ok": True,
                "source": "astra_web_widget",
                "fetched_at": datetime.now(ASTRA_TZ).isoformat(),
                "meter": meter,
            }

    def _ensure_page(self):
        if self._context is None:
            try:
                from cloakbrowser import launch_persistent_context
            except ImportError as err:
                raise AstraWebError("CloakBrowser is not installed in the sidecar") from err
            os.makedirs(self.config.profile_dir, exist_ok=True)
            self._context = launch_persistent_context(
                self.config.profile_dir,
                headless=self.config.headless,
                locale="de-DE",
                timezone="Europe/Berlin",
                args=[
                    "--remote-debugging-port=9222",
                    "--remote-debugging-address=0.0.0.0",
                    "--disable-http2",
                ],
            )
        pages = self._context.pages
        if self._page is None:
            self._page = pages[0] if pages else self._context.new_page()
        return self._page

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
            except Exception:  # noqa: BLE001
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
            except Exception:  # noqa: BLE001
                continue

    def _capture_browser_session(self) -> None:
        if self._context is None:
            return
        cookies = self._context.cookies()
        if cookies:
            self._last_cookie = "; ".join(
                f"{cookie['name']}={cookie['value']}" for cookie in cookies
            )
        for page in self._context.pages:
            parsed = urlparse(page.url)
            session_id = parse_qs(parsed.query).get("sessionId", [""])[0]
            if session_id:
                self._last_session_id = session_id
                return

    def _fetch_meter_widget(self, session_id: str, cookie: str) -> str:
        opener = build_opener()
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
        )
        widget_url = _find_widget_url(dashboard, self.config.web_base_url, session_id)
        return self._request_text(opener, widget_url, data=None, headers=headers)

    @staticmethod
    def _request_text(opener, url: str, *, data: dict[str, str] | None, headers: dict[str, str]) -> str:
        body = urlencode(data).encode() if data is not None else None
        request = Request(url, data=body, headers=headers, method="POST" if body else "GET")
        try:
            with opener.open(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as err:
            raise AstraWebError(f"Astra web returned HTTP {err.code}") from err
        except URLError as err:
            raise AstraWebError(f"Astra web request failed: {err.reason}") from err
        text = raw.decode("latin-1", errors="ignore")
        lowered = text.casefold()
        if "recaptcha" in lowered or "g-recaptcha" in lowered:
            raise AstraWebError("Astra returned a reCAPTCHA login page")
        if "cslogin" in lowered and "passwort" in lowered:
            raise AstraWebError("Astra browser session is logged out")
        if not text.strip():
            raise AstraWebError("Astra web returned an empty response")
        return text


def _find_widget_url(dashboard_html: str, base_url: str, session_id: str) -> str:
    match = re.search(r"""["']([^"']*wg_replastzs\.php[^"']*)["']""", dashboard_html)
    if match:
        return urljoin(f"{base_url}/", unescape(match.group(1)))
    return f"{base_url}/wg_replastzs.php?{urlencode({'sessionId': session_id})}"


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
if CONFIG.bind != "127.0.0.1" and not CONFIG.shared_token:
    raise ValueError("ASTRA_SHARED_TOKEN is required when binding to non-loopback addresses")
SESSION = AstraBrowserSession(CONFIG)


class Handler(BaseHTTPRequestHandler):
    server_version = "AstraBrowserProxy/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, SESSION.health())
            return
        if self.path == "/current":
            self._handle_current()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if self.path == "/login":
            try:
                self._send_json(HTTPStatus.OK, SESSION.login())
            except AstraWebError as err:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(err)})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def _handle_current(self) -> None:
        try:
            self._send_json(HTTPStatus.OK, SESSION.current())
        except AstraWebError as err:
            LOGGER.warning("Current fetch failed: %s", err)
            self._send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(err)})

    def _authorized(self) -> bool:
        if not CONFIG.shared_token:
            if CONFIG.bind == "127.0.0.1":
                return True
            return False
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
    server = ThreadingHTTPServer((CONFIG.bind, CONFIG.port), Handler)
    LOGGER.info("Starting Astra browser proxy on %s:%s", CONFIG.bind, CONFIG.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
