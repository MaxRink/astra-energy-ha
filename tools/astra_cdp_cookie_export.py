#!/usr/bin/env python3
"""Export Astra web session details from a Chrome DevTools Protocol session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import parse_qsl, quote, urlsplit

try:
    from tools.cdp_capture import WebSocket, http_json, wait_for_chrome
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.cdp_capture import WebSocket, http_json, wait_for_chrome


class SimpleCdp:
    """Minimal request/response CDP client."""

    def __init__(self, ws_url: str) -> None:
        self.ws = WebSocket(ws_url)
        self.next_id = 0

    def command(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and wait for its response."""
        self.next_id += 1
        command_id = self.next_id
        message = {"id": command_id, "method": method}
        if params is not None:
            message["params"] = params
        self.ws.send(message)
        while True:
            event = self.ws.recv()
            if event is None:
                raise RuntimeError("CDP socket closed")
            if event.get("id") == command_id:
                if "error" in event:
                    raise RuntimeError(json.dumps(event["error"], ensure_ascii=False))
                return event.get("result") or {}


def main() -> int:
    """Read cookies/sessionId from a logged-in Astra browser tab."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--domain", default="astra-cloud.com")
    parser.add_argument("--target-url", default="")
    parser.add_argument("--navigate", action="store_true")
    parser.add_argument("--write-env", type=Path)
    parser.add_argument("--print-secrets", action="store_true")
    args = parser.parse_args()

    wait_for_chrome(args.port)
    if args.navigate and args.target_url:
        http_json(
            f"http://127.0.0.1:{args.port}/json/new?{quote(args.target_url)}",
            method="PUT",
        )
    tabs = http_json(f"http://127.0.0.1:{args.port}/json/list")
    page = _select_page(tabs, args.domain)
    if page is None:
        raise RuntimeError(
            f"No Chrome page for {args.domain} found on CDP port {args.port}. "
            "Open/log in to Astra in a Chrome instance started with remote debugging."
        )

    cdp = SimpleCdp(page["webSocketDebuggerUrl"])
    cdp.command("Network.enable")
    cdp.command("Runtime.enable")
    location = _location_href(cdp) or page.get("url") or ""
    cookies = _domain_cookies(cdp.command("Network.getAllCookies"), args.domain)
    session_id = _extract_session_id(location) or _session_id_from_tabs(tabs) or _session_id_from_dom(cdp)
    cookie_header = "; ".join(f"{item['name']}={item['value']}" for item in cookies)

    summary = {
        "page": _redact_session_id(location),
        "session_id_found": bool(session_id),
        "session_id_length": len(session_id or ""),
        "cookie_count": len(cookies),
        "cookie_names": [item["name"] for item in cookies],
        "cookie_header_length": len(cookie_header),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.print_secrets:
        print(f"ASTRA_WEB_SESSION_ID={session_id or ''}")
        print(f"ASTRA_WEB_COOKIE={cookie_header}")

    if not session_id:
        raise RuntimeError("No sessionId found in the selected Astra tab URL")
    if not cookie_header:
        raise RuntimeError("No Astra cookies found through CDP")
    if args.write_env:
        _update_env(
            args.write_env,
            {
                "ASTRA_WEB_SESSION_ID": session_id,
                "ASTRA_WEB_COOKIE": cookie_header,
            },
        )
        print(f"updated {args.write_env} with redacted Astra web session values")
    return 0


def _select_page(tabs: list[dict], domain: str) -> dict | None:
    for tab in tabs:
        if tab.get("type") != "page":
            continue
        if domain in str(tab.get("url") or ""):
            return tab
    return next((tab for tab in tabs if tab.get("type") == "page"), None)


def _location_href(cdp: SimpleCdp) -> str | None:
    result = cdp.command(
        "Runtime.evaluate",
        {"expression": "location.href", "returnByValue": True},
    )
    value = ((result.get("result") or {}).get("value") or "").strip()
    return value or None


def _domain_cookies(result: dict, domain: str) -> list[dict]:
    cookies = result.get("cookies") or []
    return [
        cookie
        for cookie in cookies
        if domain in str(cookie.get("domain") or "") and cookie.get("name") and cookie.get("value")
    ]


def _extract_session_id(url: str) -> str | None:
    params = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    session_id = params.get("sessionId")
    return session_id or None


def _session_id_from_tabs(tabs: list[dict]) -> str | None:
    for tab in tabs:
        session_id = _extract_session_id(str(tab.get("url") or ""))
        if session_id:
            return session_id
    return None


def _session_id_from_dom(cdp: SimpleCdp) -> str | None:
    """Extract sessionId from the loaded Astra dashboard HTML."""
    result = cdp.command(
        "Runtime.evaluate",
        {
            "expression": (
                "(() => {"
                "const html = document.documentElement.outerHTML;"
                "const matches = [...html.matchAll(/sessionId[\\\"'=:\\\\s]*([^\\\"'&< >]{8,})/gi)]"
                ".map(m => m[1]).filter(v => /^[0-9a-f]{32}$/i.test(v));"
                "return matches[0] || '';"
                "})()"
            ),
            "returnByValue": True,
        },
    )
    value = ((result.get("result") or {}).get("value") or "").strip()
    return value or None


def _redact_session_id(url: str) -> str:
    parsed = urlsplit(url)
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        pairs.append((key, "<redacted>" if key == "sessionId" and value else value))
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in pairs)
    return parsed._replace(query=query).geturl()


def _update_env(path: Path, values: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    lines: list[str] = []
    for line in existing:
        key = line.split("=", 1)[0].strip()
        if key in values:
            lines.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            lines.append(line)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
