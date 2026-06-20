#!/usr/bin/env python3
"""Dump raw Astra Android API payloads to ignored local capture files."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import getpass
import json
from pathlib import Path
import sys

try:
    from tools.astra_mobile_probe import DEFAULT_URL, post_action, session_id
    from tools.env_loader import getenv
except ModuleNotFoundError:
    from astra_mobile_probe import DEFAULT_URL, post_action, session_id
    from env_loader import getenv

DEFAULT_ACTIONS = (
    "get_mtr_lzs",
    "get_mtr_eb",
    "get_mtr_autarkie",
    "get_mtr_vb_overview",
    "get_mtr_verbrauch",
    "get_mtr_vbmed",
    "get_mtr_hist",
    "get_mtr_inv",
    "get_verbrauch",
    "get_wf",
    "lngchg_medium_list",
)


def main() -> int:
    """Authenticate once and dump configured API actions."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=getenv("ASTRA_API_URL", DEFAULT_URL))
    parser.add_argument("--username", default=getenv("ASTRA_USERNAME"))
    parser.add_argument("--password")
    parser.add_argument("--immo", default=getenv("ASTRA_IMMO", "-1"))
    parser.add_argument("--year", default=getenv("ASTRA_YEAR", str(datetime.now().year)))
    parser.add_argument("--month", default=getenv("ASTRA_MONTH", "-1"))
    parser.add_argument("--date", default=getenv("ASTRA_DATE", "-1"))
    parser.add_argument("--medium", default=getenv("ASTRA_MEDIUM", "1"))
    parser.add_argument("--lang", default=getenv("ASTRA_LANGUAGE", "de"))
    parser.add_argument(
        "--actions",
        default=getenv("ASTRA_ACTIONS", ",".join(DEFAULT_ACTIONS)),
        help="Comma-separated Astra Android API actions to dump after login.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON path. Defaults to captures/astra-raw-<UTC timestamp>.json.",
    )
    args = parser.parse_args()

    if not args.username:
        parser.error("set ASTRA_USERNAME in .secrets.env or pass --username")
    password = args.password or getenv("ASTRA_PASSWORD") or getpass.getpass("Astra password: ")
    actions = [action.strip() for action in args.actions.split(",") if action.strip()]
    out_path = Path(args.out) if args.out else _default_output_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

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
    started_at = datetime.now(UTC).isoformat()
    capture: dict[str, object] = {
        "captured_at": started_at,
        "url": args.url,
        "request_defaults": {
            "s_immo": args.immo,
            "s_year": args.year,
            "s_med": args.medium,
            "s_lang": args.lang,
            "s_mnt": args.month,
            "s_datum": args.date,
        },
        "login": {},
        "actions": {},
    }

    login = _post_json(args.url, "auth_login", common)
    capture["login"] = login
    if str(login.get("auth")) != "1":
        _write_json(out_path, capture)
        print(f"login failed; raw response written to {out_path}", file=sys.stderr)
        return 2

    immo = str(login.get("immo_sel") or args.immo)
    common["s_immo"] = immo
    action_results: dict[str, object] = {}
    for action in actions:
        try:
            action_results[action] = {
                "ok": True,
                "payload": _post_json(args.url, action, common),
            }
        except Exception as err:  # noqa: BLE001
            action_results[action] = {
                "ok": False,
                "error": {
                    "type": type(err).__name__,
                    "message": str(err),
                },
            }
    capture["actions"] = action_results
    _write_json(out_path, capture)
    print(f"raw Astra payloads written to {out_path}")
    print("raw capture is gitignored; do not paste it into issues or commits")
    return 0


def _post_json(url: str, action: str, common: dict[str, str]) -> dict:
    """POST one API action and parse JSON."""
    return json.loads(post_action(url, action, **common))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON with stable formatting."""
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _default_output_path() -> Path:
    """Return the default ignored capture path."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("captures") / f"astra-raw-{stamp}.json"


if __name__ == "__main__":
    raise SystemExit(main())
