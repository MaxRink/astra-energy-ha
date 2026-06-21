"""Manual Astra browser-session checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from .api import ASTRA_TIME_ZONE, AstraApiError, _parse_number
from .const import DEFAULT_WEB_BASE_URL, DEFAULT_WEB_GRAPH_TOTAL_ID

if TYPE_CHECKING:
    from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)

TITLE_RE = re.compile(
    r'TITLE="[^"]* ist\s+([0-9.,-]+)\s+kWh\s+um\s+'
    r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AstraWebGraphPoint:
    """One cumulative and interval point from Astra's web graph endpoint."""

    timestamp: datetime
    cumulative_kwh: float
    interval_kwh: float


@dataclass(frozen=True)
class AstraWebSessionStatus:
    """Redaction-safe status of the optional manual browser-session fallback."""

    status: str
    checked_at: str
    message: str | None = None
    graph_id: str | None = None
    point_count: int | None = None
    response_bytes: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        """Return attributes safe to expose as diagnostics."""
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "message": self.message,
            "graph_id": self.graph_id,
            "point_count": self.point_count,
            "response_bytes": self.response_bytes,
        }


def parse_graph_points(html: str) -> list[AstraWebGraphPoint]:
    """Parse cumulative and interval values from Astra's HTML image map."""
    values_by_ts: dict[datetime, list[float]] = {}
    for raw_value, raw_ts in TITLE_RE.findall(html):
        timestamp = datetime.strptime(raw_ts, "%d.%m.%Y %H:%M:%S").replace(
            tzinfo=ASTRA_TIME_ZONE
        )
        value = _parse_number(raw_value)
        if value is None:
            continue
        values_by_ts.setdefault(timestamp, []).append(value)

    points: list[AstraWebGraphPoint] = []
    for timestamp, values in sorted(values_by_ts.items()):
        positives = [value for value in values if value >= 0]
        if not positives:
            continue
        points.append(
            AstraWebGraphPoint(
                timestamp=timestamp,
                cumulative_kwh=max(positives),
                interval_kwh=min(positives),
            )
        )
    return points


def classify_web_response(html: str, point_count: int) -> tuple[str, str | None]:
    """Classify graph HTML without exposing cookies or session IDs."""
    if point_count:
        return "ok", None
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = re.sub(r"\s+", " ", unescape(plain)).strip()
    lower = plain.casefold()
    raw_lower = html.casefold()
    if "recaptcha" in raw_lower or "g-recaptcha" in raw_lower:
        return "login_required", "Astra returned a login page with reCAPTCHA"
    login_markers = (
        "cslogin",
        "customlogin",
        "benutzername",
        "passwort",
        "username",
        "password",
    )
    if any(marker in lower or marker in raw_lower for marker in login_markers):
        return "login_required", "Astra returned a login page; the browser session is logged out"
    session_markers = (
        "session expired",
        "session abgelaufen",
        "session ist abgelaufen",
        "ungültige session",
        "invalid session",
    )
    if any(marker in lower for marker in session_markers):
        return "expired", "Astra rejected the browser session"
    if not html.strip():
        return "invalid_response", "Astra returned an empty web graph response"
    return "no_data", "Astra web graph response contained no parseable data points"


async def async_check_web_session(
    session: ClientSession,
    *,
    base_url: str = DEFAULT_WEB_BASE_URL,
    session_id: str | None,
    cookie: str | None,
    graph_id: str = DEFAULT_WEB_GRAPH_TOTAL_ID,
) -> AstraWebSessionStatus:
    """Fetch one web graph to verify a manual browser session."""
    checked_at = datetime.now(ASTRA_TIME_ZONE).isoformat()
    if not session_id and not cookie:
        return AstraWebSessionStatus(status="not_configured", checked_at=checked_at)
    if not session_id:
        return AstraWebSessionStatus(
            status="missing_session_id",
            checked_at=checked_at,
            message="Astra web fallback is enabled but no sessionId is configured",
            graph_id=graph_id,
        )
    if not graph_id:
        return AstraWebSessionStatus(
            status="missing_graph_id",
            checked_at=checked_at,
            message="Astra web fallback is enabled but no graph ID is configured",
            graph_id=graph_id,
        )
    if not cookie:
        return AstraWebSessionStatus(
            status="missing_cookie",
            checked_at=checked_at,
            message="Astra web fallback is enabled but no Cookie header is configured",
            graph_id=graph_id,
        )

    now = datetime.now(ASTRA_TIME_ZONE).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=24)
    html = ""
    try:
        async with session.get(
            _graph_url(
                base_url=base_url,
                session_id=session_id,
                graph_id=graph_id,
                start=start,
                end=now,
            ),
            headers={
                "User-Agent": "Mozilla/5.0 AstraEnergyHomeAssistant/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Cookie": cookie,
            },
        ) as response:
            html = await response.text(encoding="latin-1", errors="ignore")
            if response.status >= 400:
                return AstraWebSessionStatus(
                    status="unreachable",
                    checked_at=checked_at,
                    message=f"Astra web graph returned HTTP {response.status}",
                    graph_id=graph_id,
                    response_bytes=len(html.encode("latin-1", errors="ignore")),
                )
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Astra web session check failed: %s", err)
        return AstraWebSessionStatus(
            status="unreachable",
            checked_at=checked_at,
            message=f"Astra web session check failed: {type(err).__name__}: {err}",
            graph_id=graph_id,
        )

    points = parse_graph_points(html)
    status, message = classify_web_response(html, len(points))
    return AstraWebSessionStatus(
        status=status,
        checked_at=checked_at,
        message=message,
        graph_id=graph_id,
        point_count=len(points),
        response_bytes=len(html.encode("latin-1", errors="ignore")),
    )


def _graph_url(
    *,
    base_url: str,
    session_id: str,
    graph_id: str,
    start: datetime,
    end: datetime,
) -> str:
    base = base_url.rstrip("/")
    if not base.endswith("pm_graph.php"):
        base = f"{base}/pm_graph.php"
    start_provider = start.strftime("%d.%m.%Y %H:%M:%S")
    end_provider = end.strftime("%d.%m.%Y %H:%M:%S")
    start_iso = start.strftime("%Y-%m-%d %H:%M:%S")
    end_iso = end.strftime("%Y-%m-%d %H:%M:%S")
    params = {
        "sessionId": session_id,
        "s_vom": start_provider,
        "s_bis": end_provider,
        "s_tvom": start_iso,
        "s_tbis": end_iso,
        "s_bvom": start_iso,
        "s_bbis": end_iso,
        "id": graph_id,
        "s_prod": "",
        "s_width": "800",
        "s_height": "400",
    }
    return f"{base}?{urlencode(params)}"


class AstraWebSessionError(AstraApiError):
    """Astra browser-session fallback is configured but not usable."""
