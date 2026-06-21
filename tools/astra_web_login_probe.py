#!/usr/bin/env python3
"""Probe Astra browser login behavior without storing credentials in output."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    from tools.env_loader import getenv
except ModuleNotFoundError:
    from env_loader import getenv

DEFAULT_LOGIN_URL = "https://astra-cloud.com/readyxnet/source/login/csloginw.php"
DEFAULT_FLARESOLVERR_URL = "http://192.168.1.104:31027/v1"
DEFAULT_BYPARR_URL = "http://192.168.1.104:30230/v1"
USER_AGENT = "Mozilla/5.0 AstraEnergyWebLoginProbe/1.0"


def main() -> int:
    """Run login-page and anti-bot helper probes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--login-url", default=getenv("ASTRA_WEB_LOGIN_URL", DEFAULT_LOGIN_URL))
    parser.add_argument("--username", default=getenv("ASTRA_USERNAME"))
    parser.add_argument("--password", default=getenv("ASTRA_PASSWORD"))
    parser.add_argument("--flaresolverr-url", default=getenv("FLARESOLVERR_URL", DEFAULT_FLARESOLVERR_URL))
    parser.add_argument("--byparr-url", default=getenv("BYPARR_URL", DEFAULT_BYPARR_URL))
    parser.add_argument("--skip-submit", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {"login_url": args.login_url}
    result["direct_get"] = _direct_get(args.login_url)
    result["flaresolverr_get"] = _proxy_get(
        args.flaresolverr_url,
        args.login_url,
        timeout_field="maxTimeout",
        timeout_value=45_000,
    )
    result["byparr_get"] = _proxy_get(
        args.byparr_url,
        args.login_url,
        timeout_field="max_timeout",
        timeout_value=45,
    )
    if not args.skip_submit:
        if not args.username or not args.password:
            parser.error("set ASTRA_USERNAME/ASTRA_PASSWORD or pass --skip-submit")
        result["direct_submit"] = _direct_submit(args.login_url, args.username, args.password)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def _direct_get(url: str) -> dict[str, Any]:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    started = time.time()
    try:
        with opener.open(_request(url), timeout=30) as response:
            html = response.read().decode("latin-1", errors="ignore")
        return {
            "ok": True,
            "elapsed_seconds": round(time.time() - started, 3),
            "status": response.status,
            **_html_summary(html),
            "cookies": [cookie.name for cookie in jar],
        }
    except Exception as err:  # noqa: BLE001
        return _error_result(err, started)


def _direct_submit(url: str, username: str, password: str) -> list[dict[str, Any]]:
    variants = [
        ("missing_recaptcha", {}),
        ("empty_recaptcha", {"g-recaptcha-response": ""}),
        ("bogus_recaptcha", {"g-recaptcha-response": "probe-not-a-valid-token"}),
    ]
    results = []
    for name, extra in variants:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        opener.open(_request(url), timeout=30).read()
        form = {
            "UserName": username,
            "Password": password,
            "Email": username,
            "strRequestType": "Submit",
            "EULA_OK": "0",
            "userEULA": "",
            "bActivationFlag": "NOCHECK",
            "iCounter": "0",
            **extra,
        }
        started = time.time()
        try:
            with opener.open(_request(url, form), timeout=30) as response:
                html = response.read().decode("latin-1", errors="ignore")
            summary = _html_summary(html)
            results.append(
                {
                    "case": name,
                    "ok": True,
                    "elapsed_seconds": round(time.time() - started, 3),
                    "status": response.status,
                    "login_succeeded": summary["has_pm_customlogin"] or summary["has_sessionid"],
                    **summary,
                    "cookies": [cookie.name for cookie in jar],
                }
            )
        except Exception as err:  # noqa: BLE001
            results.append({"case": name, **_error_result(err, started)})
    return results


def _proxy_get(endpoint: str | None, url: str, *, timeout_field: str, timeout_value: int) -> dict[str, Any]:
    if not endpoint:
        return {"ok": False, "error": "not_configured"}
    payload = {
        "cmd": "request.get",
        "url": url,
        timeout_field: timeout_value,
    }
    started = time.time()
    try:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        client_timeout = 75 if timeout_field == "maxTimeout" else max(75, int(timeout_value) + 15)
        with urllib.request.urlopen(request, timeout=client_timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        solution = data.get("solution") or {}
        html = solution.get("response") or ""
        return {
            "ok": True,
            "elapsed_seconds": round(time.time() - started, 3),
            "status": data.get("status"),
            "message": data.get("message"),
            "version": data.get("version"),
            "solution_status": solution.get("status"),
            "solution_url": solution.get("url"),
            **_html_summary(html),
            "cookies": [cookie.get("name") for cookie in solution.get("cookies") or []],
        }
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "elapsed_seconds": round(time.time() - started, 3),
            "error": type(err).__name__,
            "status": err.code,
            "body_preview": _clean_text(body),
        }
    except Exception as err:  # noqa: BLE001
        return _error_result(err, started)


def _request(url: str, form: dict[str, str] | None = None) -> urllib.request.Request:
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    return urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded" if data else "text/html",
        },
        method="POST" if data else "GET",
    )


def _html_summary(html: str) -> dict[str, Any]:
    match = re.search(
        r"render=([^\"&]+)|g_recaptcha_site_key\s*=\s*'([^']+)'|data-sitekey=[\"']([^\"']+)",
        html,
    )
    return {
        "html_len": len(html),
        "has_recaptcha": "recaptcha" in html.lower(),
        "sitekey": next((group for group in (match.groups() if match else []) if group), None),
        "has_pm_customlogin": "pm_customlogin" in html.lower(),
        "has_sessionid": "sessionid" in html.lower(),
        "title": _title(html),
        "snippet": _clean_text(re.sub(r"<[^>]+>", " ", html))[:240],
    }


def _title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return _clean_text(match.group(1)) if match else None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _error_result(err: Exception, started: float) -> dict[str, Any]:
    return {
        "ok": False,
        "elapsed_seconds": round(time.time() - started, 3),
        "error": type(err).__name__,
        "message": str(err),
    }


if __name__ == "__main__":
    raise SystemExit(main())
