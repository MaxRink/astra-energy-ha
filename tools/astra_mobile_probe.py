#!/usr/bin/env python3
"""Probe Astra's Android JSON API without Home Assistant dependencies."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    from tools.env_loader import getenv
except ModuleNotFoundError:
    from env_loader import getenv

DEFAULT_URL = "https://astra-cloud.com/readyxnet/source/login/csandroid.php"


def md5_hex(value: str) -> str:
    """Return lowercase MD5 hex digest."""
    return hashlib.md5(value.encode()).hexdigest()


def checksum(action: str, timestamp: str) -> str:
    """Return Astra Android request checksum."""
    return md5_hex(f"SNAFU{action}{timestamp}")


def session_id(username: str, password: str) -> str:
    """Return Astra Android session id."""
    return md5_hex(f"{username}{md5_hex(password)}")


def post_raw(url: str, payload: dict[str, str]) -> str:
    """POST form data and return checksum-verified payload text."""
    body = urllib.parse.urlencode({**payload, "s_dv": "1"}).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode()
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"HTTP {err.code}") from err
    if len(text) < 32:
        raise RuntimeError("Astra response is too short")
    payload_text = text[:-32]
    response_checksum = text[-32:]
    if md5_hex(payload_text) != response_checksum:
        raise RuntimeError("Astra response checksum mismatch")
    return payload_text


def post_action(url: str, action: str, **params: str) -> str:
    """POST one signed Astra action."""
    timestamp = post_raw(
        url,
        {
            "s_action": "get_ts",
            "s_ts": "",
            "s_cs": checksum("get_ts", ""),
        },
    )
    return post_raw(
        url,
        {
            "s_action": action,
            "s_ts": timestamp,
            "s_cs": checksum(action, timestamp),
            **params,
        },
    )


def main() -> int:
    """Run a minimal login and endpoint probe."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=getenv("ASTRA_API_URL", DEFAULT_URL))
    parser.add_argument("--username", default=getenv("ASTRA_USERNAME"))
    parser.add_argument("--password")
    parser.add_argument("--action", default=getenv("ASTRA_ACTION", "get_mtr_lzs"))
    parser.add_argument("--immo", default=getenv("ASTRA_IMMO", "-1"))
    parser.add_argument("--year", default=getenv("ASTRA_YEAR", "2026"))
    parser.add_argument("--month", default=getenv("ASTRA_MONTH", "-1"))
    parser.add_argument("--date", default=getenv("ASTRA_DATE", "-1"))
    parser.add_argument("--medium", default=getenv("ASTRA_MEDIUM", "1"))
    parser.add_argument("--lang", default=getenv("ASTRA_LANGUAGE", "de"))
    args = parser.parse_args()

    if not args.username:
        parser.error("set ASTRA_USERNAME in .secrets.env or pass --username")
    password = args.password or getenv("ASTRA_PASSWORD") or getpass.getpass("Astra password: ")
    sid = session_id(args.username, password)
    common = {
        "s_sid": sid,
        "s_immo": args.immo,
        "s_year": args.year,
        "s_med": args.medium,
        "s_lang": args.lang,
        "s_mnt": args.month,
        "s_datum": args.date,
    }
    login = json.loads(post_action(args.url, "auth_login", **common))
    print(
        json.dumps(
            {
                "auth": login.get("auth"),
                "company": bool(login.get("comp_id")),
                "selected_location": login.get("immo_sel"),
                "is_tenant": login.get("is_mieter"),
                "medium_count": len(login.get("med_list") or []),
                "location_count": len(login.get("standort_list") or []),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if str(login.get("auth")) != "1":
        return 2
    immo = str(login.get("immo_sel") or args.immo)
    result = json.loads(post_action(args.url, args.action, **{**common, "s_immo": immo}))
    rows = result.get("data") or []
    print(
        json.dumps(
            {
                "action": args.action,
                "auth": result.get("auth"),
                "keys": sorted(result.keys()),
                "row_count": len(rows) if isinstance(rows, list) else None,
                "first_row_keys": sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else [],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
