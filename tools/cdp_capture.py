#!/usr/bin/env python3
"""Capture Astra browser traffic through Chrome DevTools Protocol.

This tool intentionally writes raw JSONL into `captures/`, which is gitignored.
Raw captures can contain credentials, cookies, tokens, meter IDs, and private
usage data.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import selectors
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit


def http_json(url: str, *, method: str = "GET") -> dict:
    """Read JSON from Chrome's debugging HTTP endpoint."""
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


class WebSocket:
    """Tiny RFC 6455 client sufficient for CDP JSON frames."""

    def __init__(self, url: str) -> None:
        parsed = urlsplit(url)
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        self._path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        raw = socket.create_connection((self._host, self._port), timeout=10)
        if parsed.scheme == "wss":
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=self._host)
        self.sock = raw
        self.sock.setblocking(False)
        self._handshake()

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.setblocking(True)
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.sock.recv(4096)
        if b" 101 " not in resp and b" 101\r\n" not in resp:
            raise RuntimeError(f"WebSocket upgrade failed: {resp[:300]!r}")
        self.sock.setblocking(False)

    def send(self, obj: dict) -> None:
        """Send one JSON object."""
        data = json.dumps(obj, separators=(",", ":")).encode()
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        length = len(data)
        if length <= 125:
            header = bytes([0x81, 0x80 | length]) + mask
        elif length <= 65535:
            header = bytes([0x81, 0xFE]) + struct.pack(">H", length) + mask
        else:
            header = bytes([0x81, 0xFF]) + struct.pack(">Q", length) + mask
        self.sock.sendall(header + masked)

    def recv(self) -> dict | None:
        """Receive one JSON object if available."""
        self.sock.setblocking(True)
        try:
            header = self.sock.recv(2)
            if not header:
                return None
            b1, b2 = header
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if b2 & 0x80 else None
            payload = self._read_exact(length)
            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            if opcode == 8:
                return None
            if opcode == 9:
                return {}
            return json.loads(payload.decode())
        finally:
            self.sock.setblocking(False)

    def _read_exact(self, size: int) -> bytes:
        buf = b""
        while len(buf) < size:
            chunk = self.sock.recv(size - len(buf))
            if not chunk:
                raise EOFError("socket closed")
            buf += chunk
        return buf


class CdpClient:
    """Small CDP client."""

    def __init__(self, ws_url: str, out: Path) -> None:
        self.ws = WebSocket(ws_url)
        self.out = out
        self.next_id = 0
        self.pending: dict[int, str] = {}
        self.response_body_requests: dict[int, str] = {}
        self.loading_finished: set[str] = set()

    def command(self, method: str, params: dict | None = None) -> int:
        """Send a CDP command."""
        self.next_id += 1
        msg = {"id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.pending[self.next_id] = method
        self.ws.send(msg)
        return self.next_id

    def run(self) -> None:
        """Run capture until interrupted."""
        selector = selectors.DefaultSelector()
        selector.register(self.ws.sock, selectors.EVENT_READ)
        with self.out.open("a") as fh:
            while True:
                for _key, _mask in selector.select(timeout=1.0):
                    event = self.ws.recv()
                    if event is None:
                        return
                    self._write(fh, event)
                    self._maybe_fetch_body(event)

    def _write(self, fh, event: dict) -> None:
        if "id" in event and isinstance(event["id"], int):
            cdp_id = event["id"]
            if cdp_id in self.pending:
                event["_cdp_command"] = self.pending.pop(cdp_id)
            if cdp_id in self.response_body_requests:
                event["_cdp_request_id"] = self.response_body_requests.pop(cdp_id)
        event["_captured_at"] = time.time()
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        fh.flush()

    def _maybe_fetch_body(self, event: dict) -> None:
        if event.get("method") != "Network.loadingFinished":
            return
        request_id = event.get("params", {}).get("requestId")
        if request_id:
            command_id = self.command("Network.getResponseBody", {"requestId": request_id})
            self.response_body_requests[command_id] = request_id


def wait_for_chrome(port: int) -> None:
    """Wait until Chrome debugging endpoint is available."""
    deadline = time.time() + 30
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            http_json(f"http://127.0.0.1:{port}/json/version")
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
            last_error = err
            time.sleep(0.5)
    raise RuntimeError(f"Chrome CDP endpoint did not start: {last_error}")


def launch_chrome(chrome_path: str, port: int, user_data_dir: Path) -> subprocess.Popen:
    """Launch isolated Chrome for capture."""
    return subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--new-window",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target-url", default="https://astra-cloud.com/astra04/readyxnet/source/pm/"
    )
    parser.add_argument("--out", type=Path, default=Path("captures/web-login.jsonl"))
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--launch-chrome", action="store_true")
    parser.add_argument(
        "--chrome-path",
        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    parser.add_argument("--user-data-dir", type=Path)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    user_data_dir = args.user_data_dir or Path(tempfile.mkdtemp(prefix="astra-cdp-profile-"))
    chrome: subprocess.Popen | None = None

    if args.launch_chrome:
        chrome = launch_chrome(args.chrome_path, args.port, user_data_dir)
        print(f"launched Chrome pid={chrome.pid} profile={user_data_dir}")

    wait_for_chrome(args.port)
    tabs = http_json(f"http://127.0.0.1:{args.port}/json/list")
    page = next((tab for tab in tabs if tab.get("type") == "page"), None)
    if page is None:
        page = http_json(
            f"http://127.0.0.1:{args.port}/json/new?{quote('about:blank')}",
            method="PUT",
        )
    ws_url = page["webSocketDebuggerUrl"]

    client = CdpClient(ws_url, args.out)
    for method, params in [
        (
            "Network.enable",
            {"maxTotalBufferSize": 100_000_000, "maxResourceBufferSize": 25_000_000},
        ),
        ("Page.enable", None),
        ("Runtime.enable", None),
        ("Network.setCacheDisabled", {"cacheDisabled": True}),
        ("Runtime.evaluate", {"expression": "window.name = 'astra_cdp_capture'; undefined"}),
        ("Page.navigate", {"url": args.target_url}),
    ]:
        client.command(method, params)

    print(f"capturing CDP traffic to {args.out}")
    print("log in and browse Astra usage views; press Ctrl-C here when done")
    try:
        client.run()
    except KeyboardInterrupt:
        print("\nstopped capture")
    finally:
        if chrome and chrome.poll() is None:
            print(f"Chrome is still running with profile {user_data_dir}; close it when done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
