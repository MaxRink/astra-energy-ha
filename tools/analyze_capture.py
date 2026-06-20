#!/usr/bin/env python3
"""Summarize raw CDP JSONL captures into endpoint documentation."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

INITIAL_CAPTURE_COMMAND_COUNT = 6

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-csrf-token",
    "x-xsrf-token",
}

SENSITIVE_KEYS = {
    "c_immoid",
    "c_mieterid",
    "c_user",
    "email",
    "g-recaptcha-response",
    "password",
    "sessionid",
    "sid",
    "userid",
    "username",
}

INTERESTING_PATHS = (
    "/source/login/",
    "/source/pm/",
)

NOISY_EXTENSIONS = (
    ".css",
    ".gif",
    ".ico",
    ".jpg",
    ".jpeg",
    ".png",
)


def redact_headers(headers: dict | None) -> dict:
    """Redact sensitive headers."""
    out = {}
    for key, value in (headers or {}).items():
        out[key] = "<redacted>" if key.lower() in SENSITIVE_HEADERS else value
    return out


def is_sensitive_key(key: str) -> bool:
    """Return whether a request key is sensitive."""
    return key.lower() in SENSITIVE_KEYS


def redact_mapping(values: dict | None) -> dict:
    """Redact sensitive request values while preserving schema."""
    out = {}
    for key, value in (values or {}).items():
        if is_sensitive_key(key):
            out[key] = "<redacted>"
        elif isinstance(value, str):
            out[key] = redact_text(value)
        else:
            out[key] = value
    return out


def redact_text(value: str) -> str:
    """Redact common sensitive URL/body fields from sample text."""
    value = re.sub(
        r"(?i)\b(sessionId|sId|C_USER|C_IMMOID|C_MIETERID|UserName|Password|Email|userId|g-recaptcha-response)=([^&\s\"']+)",
        r"\1=<redacted>",
        value,
    )
    value = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>", value)
    return value


def parse_post_data(post_data: str | None) -> tuple[str | None, dict]:
    """Decode JSON or form POST data into a schema-oriented summary."""
    if not post_data:
        return None, {}
    stripped = post_data.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            return "raw", {"sample": redact_text(stripped[:200])}
        summary: dict = {
            "json_keys": sorted(obj.keys()),
        }
        if "method" in obj:
            summary["rpc_method"] = obj["method"]
        params = obj.get("params")
        if isinstance(params, list) and params and isinstance(params[0], dict):
            summary["param_keys"] = sorted(params[0].keys())
            summary["params"] = redact_mapping(params[0])
        return "json", summary
    form = dict(parse_qsl(stripped, keep_blank_values=True))
    if form:
        return "form", {"form_keys": sorted(form.keys()), "form": redact_mapping(form)}
    return "raw", {"sample": redact_text(stripped[:200])}


def is_interesting(url: str) -> bool:
    """Return whether an endpoint belongs to the Astra app surface."""
    parsed = urlsplit(url)
    path = parsed.path.lower()
    if path.endswith(NOISY_EXTENSIONS):
        return False
    return any(part in path for part in INTERESTING_PATHS)


def endpoint_key(url: str) -> str:
    """Normalize URL for grouping."""
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def body_text(result: dict | None) -> str | None:
    """Return decoded response body text when CDP captured it as text."""
    if not result or result.get("base64Encoded"):
        return None
    body = result.get("body")
    return body if isinstance(body, str) else None


def summarize_body(body: str | None) -> dict:
    """Extract schema hints from captured HTML/JSON bodies."""
    if not body:
        return {}
    summary: dict = {"body_bytes": len(body.encode(errors="ignore"))}
    stripped = body.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            summary["response_json_keys"] = sorted(obj.keys())
            content = obj.get("result", {}).get("content")
            if isinstance(content, list):
                summary["response_content_items"] = len(content)
                snippets = []
                for item in content[:3]:
                    if isinstance(item, dict):
                        keys = sorted(item.keys())
                        snippets.append(f"keys={keys}")
                if snippets:
                    summary["response_content_schema"] = snippets
    refs = sorted(
        {
            redact_text(unescape(match))
            for match in re.findall(r"""(?i)(?:href|src|action)=["']([^"']+)["']""", body)
            if ".php" in match or ".js" in match
        }
    )
    if refs:
        summary["linked_php_js"] = refs[:20]
    text = unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text)
    labels = [
        label
        for label in (
            "Geraet",
            "Gerät",
            "Verbrauch",
            "Zaehlerstand",
            "Zählerstand",
            "kWh",
            "Mieterstrom",
            "Rechnung",
            "Warnwert",
            "Grenzwert",
        )
        if label in text
    ]
    if labels:
        summary["text_hints"] = labels
    return summary


def format_value(value) -> str:
    """Format nested values compactly for markdown."""
    if value in (None, {}, [], ""):
        return "none"
    if isinstance(value, (dict, list)):
        return "`" + json.dumps(value, ensure_ascii=False, sort_keys=True) + "`"
    return f"`{value}`"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--out", type=Path, default=Path("docs/api-web-capture.md"))
    args = parser.parse_args()

    requests: dict[str, dict] = {}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    websocket_frames: list[dict] = []
    command_bodies: dict[int, dict] = {}
    loading_command_map: dict[int, str] = {}
    next_body_command_id = INITIAL_CAPTURE_COMMAND_COUNT

    with args.capture.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            event = json.loads(line)
            method = event.get("method")
            params = event.get("params", {})
            if method == "Network.requestWillBeSent":
                req = params.get("request", {})
                request_id = params.get("requestId")
                post_kind, post_summary = parse_post_data(req.get("postData"))
                item = {
                    "request_id": request_id,
                    "method": req.get("method"),
                    "url": req.get("url"),
                    "headers": redact_headers(req.get("headers")),
                    "post_kind": post_kind,
                    "post_summary": post_summary,
                    "status": None,
                    "mime": None,
                    "response_headers": {},
                    "query": redact_mapping(dict(parse_qsl(urlsplit(req.get("url", "")).query))),
                    "body_summary": {},
                }
                requests[request_id] = item
                groups[(item["method"], endpoint_key(item["url"]))].append(item)
            elif method == "Network.responseReceived":
                request_id = params.get("requestId")
                response = params.get("response", {})
                if request_id in requests:
                    requests[request_id]["status"] = response.get("status")
                    requests[request_id]["mime"] = response.get("mimeType")
                    requests[request_id]["response_headers"] = redact_headers(
                        response.get("headers")
                    )
            elif method == "Network.loadingFinished":
                request_id = params.get("requestId")
                if request_id:
                    next_body_command_id += 1
                    loading_command_map[next_body_command_id] = request_id
            elif method and method.startswith("Network.webSocketFrame"):
                websocket_frames.append(event)
            elif "id" in event and "result" in event:
                command_bodies[event["id"]] = event["result"]
                request_id = event.get("_cdp_request_id") or loading_command_map.get(event["id"])
                if request_id in requests:
                    requests[request_id]["body_summary"] = summarize_body(
                        body_text(event["result"])
                    )

    lines = [
        "# Astra Web Capture Summary",
        "",
        f"Source capture: `{args.capture}`",
        "",
        "Sensitive values are redacted. Raw captures stay local and are gitignored.",
        "",
        "## Endpoints",
        "",
    ]

    interesting_groups = {
        key: value for key, value in groups.items() if is_interesting(key[1])
    }

    for (http_method, url), items in sorted(interesting_groups.items(), key=lambda kv: kv[0]):
        statuses = sorted({str(item.get("status")) for item in items if item.get("status")})
        mimes = sorted({str(item.get("mime")) for item in items if item.get("mime")})
        sample = items[-1]
        lines.extend(
            [
                f"### `{http_method} {url}`",
                "",
                f"- Seen: `{len(items)}` time(s)",
                f"- Statuses: `{', '.join(statuses) or 'unknown'}`",
                f"- MIME types: `{', '.join(mimes) or 'unknown'}`",
                f"- Query: {format_value(sample.get('query'))}",
                f"- Request body kind: `{sample.get('post_kind') or 'none observed'}`",
                f"- Request body summary: {format_value(sample.get('post_summary'))}",
                f"- Response body hints: {format_value(sample.get('body_summary'))}",
                "- Auth/session: inspect raw capture locally; sensitive headers are redacted here.",
                "",
            ]
        )

    ajax_methods: dict[str, list[dict]] = defaultdict(list)
    linked_refs = set()
    report_variants = []
    for item in requests.values():
        url = item.get("url") or ""
        path = urlsplit(url).path
        post_summary = item.get("post_summary") or {}
        rpc_method = post_summary.get("rpc_method")
        if path.endswith("/ajax.php") and rpc_method:
            ajax_methods[rpc_method].append(item)
        for ref in (item.get("body_summary") or {}).get("linked_php_js", []):
            linked_refs.add(ref)
        if path.endswith("/pm_repeaverbr.php"):
            query = item.get("query") or {}
            report_variants.append(
                {
                    "Report": query.get("Report"),
                    "s_year": query.get("s_year"),
                    "s_fday": query.get("s_fday"),
                    "s_rmnt": query.get("s_rmnt"),
                    "body_hints": (item.get("body_summary") or {}).get("text_hints"),
                }
            )

    lines.extend(["## AJAX RPC Methods", ""])
    for rpc_method, items in sorted(ajax_methods.items()):
        sample_params = (items[-1].get("post_summary") or {}).get("params", {})
        lines.extend(
            [
                f"### `{rpc_method}`",
                "",
                f"- Seen: `{len(items)}` time(s)",
                f"- Sample params: {format_value(sample_params)}",
                "",
            ]
        )

    lines.extend(["## Report Variants", ""])
    for variant in report_variants:
        lines.append(f"- {format_value(variant)}")
    lines.append("")

    lines.extend(["## Linked Hidden PHP/JS References", ""])
    for ref in sorted(linked_refs):
        lines.append(f"- `{ref}`")
    lines.append("")

    lines.extend(
        [
            "## WebSocket Frames",
            "",
            f"- Captured WebSocket frame events: `{len(websocket_frames)}`",
            "",
            "## Follow-up",
            "",
            "- Promote confirmed endpoint schemas into `docs/api.md`.",
            "- Do not commit the raw capture.",
        ]
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
