#!/usr/bin/env python3
"""Probe Astra mobile API action names and summarize response schemas."""

from __future__ import annotations

import argparse
from datetime import datetime
import getpass
import json
from pathlib import Path

try:
    from tools.astra_mobile_probe import DEFAULT_URL, post_action, session_id
    from tools.env_loader import getenv
except ModuleNotFoundError:
    from astra_mobile_probe import DEFAULT_URL, post_action, session_id
    from env_loader import getenv

DEFAULT_ACTIONS = (
    "get_mtr_preis",
    "get_mtr_price",
    "get_mtr_tarif",
    "get_mtr_tariff",
    "get_mtr_cost",
    "get_mtr_kosten",
    "get_mtr_rechnung",
    "get_mtr_docs",
    "get_mtr_zs3",
    "get_mtr_tddview",
    "get_mtr_repeaverbr",
    "get_mtr_repeavbenrvr",
    "get_mtr_prbzgww",
    "get_mtr_graph",
    "get_gemeinstrom",
    "get_mtr_gemeinstrom",
    "get_allgemeinstrom",
    "get_mtr_allgemeinstrom",
    "get_hausstrom",
    "get_mtr_hausstrom",
    "get_objektstrom",
    "get_mtr_objektstrom",
    "get_netzstrom",
    "get_mtr_netzstrom",
    "get_solarstrom",
    "get_mtr_solarstrom",
    "get_batterie",
    "get_mtr_batterie",
    "get_energy_balance",
    "get_mtr_energy_balance",
    "get_energiebilanz",
    "get_mtr_energiebilanz",
    "get_medium_list",
    "get_mtr_medium_list",
    "get_standort_list",
    "get_mtr_standort_list",
    "get_userdocs",
    "get_mtr_userdocs",
)


def main() -> int:
    """Run bounded Android API action discovery."""
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
        default=getenv("ASTRA_DISCOVERY_ACTIONS", ",".join(DEFAULT_ACTIONS)),
        help="Comma-separated candidate action names.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON output path. Output contains schemas, not raw payloads.",
    )
    args = parser.parse_args()

    if not args.username:
        parser.error("set ASTRA_USERNAME in .secrets.env or pass --username")
    password = args.password or getenv("ASTRA_PASSWORD") or getpass.getpass("Astra password: ")
    common = {
        "s_sid": session_id(args.username, password),
        "s_immo": args.immo,
        "s_year": args.year,
        "s_med": args.medium,
        "s_lang": args.lang,
        "s_mnt": args.month,
        "s_datum": args.date,
    }
    try:
        login = _post_json(args.url, "auth_login", common)
    except Exception as err:  # noqa: BLE001
        result = {
            "login": {
                "ok": False,
                "error_type": type(err).__name__,
                "error": str(err),
            },
            "actions": [],
        }
        _emit(result, args.out)
        return 2

    login_summary = _summarize_payload(login)
    login_summary["ok"] = str(login.get("auth")) == "1"
    if not login_summary["ok"]:
        _emit({"login": login_summary, "actions": []}, args.out)
        return 2

    common["s_immo"] = str(login.get("immo_sel") or common["s_immo"])
    action_summaries = []
    for action in _split_actions(args.actions):
        try:
            payload = _post_json(args.url, action, common)
        except Exception as err:  # noqa: BLE001
            action_summaries.append(
                {
                    "action": action,
                    "ok": False,
                    "error_type": type(err).__name__,
                    "error": str(err),
                }
            )
            continue
        summary = _summarize_payload(payload)
        summary["action"] = action
        summary["ok"] = str(payload.get("auth")) == "1"
        action_summaries.append(summary)

    _emit({"login": login_summary, "actions": action_summaries}, args.out)
    return 0


def _post_json(url: str, action: str, common: dict[str, str]) -> dict:
    """POST one API action and parse JSON."""
    return json.loads(post_action(url, action, **common))


def _split_actions(value: str) -> list[str]:
    """Return unique action names preserving input order."""
    actions = []
    seen = set()
    for action in value.split(","):
        action = action.strip()
        if action and action not in seen:
            actions.append(action)
            seen.add(action)
    return actions


def _summarize_payload(payload: dict) -> dict[str, object]:
    """Return a schema-only summary without raw values."""
    rows = payload.get("data")
    first_row_keys: list[str] = []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        first_row_keys = sorted(rows[0])
    return {
        "auth": payload.get("auth"),
        "keys": sorted(payload),
        "row_count": len(rows) if isinstance(rows, list) else None,
        "first_row_keys": first_row_keys,
        "medium_count": len(payload.get("med_list") or []),
        "location_count": len(payload.get("standort_list") or []),
    }


def _emit(result: dict[str, object], out_path: Path | None) -> None:
    """Print and optionally write the discovery summary."""
    text = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
    print(text)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
