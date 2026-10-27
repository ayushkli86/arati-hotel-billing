#!/usr/bin/env python3
"""Arati Hotel — desktop-style launcher.

Starts the webapp on a private localhost-only server, then opens it in a
native-looking app window (Chrome app mode: no URL bar, no tabs). Closing
the window shuts the server down, like a normal desktop program.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PROFILE_DIR = Path.home() / ".arati-hotel" / "app-profile"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    url = f"http://{HOST}:{port}/healthz"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Server did not start in time")


def main() -> int:
    port_env = os.environ.get("ARATI_WEB_PORT")
    port = int(port_env) if port_env else _free_port()

    import uvicorn
    from webapp.main import app  # noqa: PLC0415

    config = uvicorn.Config(app, host=HOST, port=port, log_level="error")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    _wait_for_server(port)

    url = f"http://{HOST}:{port}"
    chrome_candidates = ["google-chrome", "chromium", "chromium-browser"]
    chrome = next((c for c in chrome_candidates if shutil_which(c)), None)

    if chrome:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        cmd = [
            chrome,
            "--app=" + url,
            "--user-data-dir=" + str(PROFILE_DIR),
            "--class=billedin",
            "--window-size=1600,950",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        proc = subprocess.Popen(cmd)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
    else:
        print(f"No app-capable browser found — open {url} manually. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    print("Closing Arati Hotel...")
    server.should_exit = True
    server_thread.join(timeout=5)
    return 0


def shutil_which(cmd: str):
    from shutil import which  # noqa: PLC0415
    return which(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
