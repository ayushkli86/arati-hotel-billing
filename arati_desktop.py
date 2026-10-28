#!/usr/bin/env python3
"""Arati Hotel — desktop-style launcher.

Prepares the database, applies schema upgrades, seeds a new install, starts the
webapp on a private localhost-only server, then opens it in a native-looking app
window (Chrome app mode: no URL bar, no tabs). Closing the window shuts the
server down, like a normal desktop program.
"""
from __future__ import annotations

import fcntl
import logging
import os
import shutil
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
APP_DIR = Path.home() / ".arati-hotel"
PROFILE_DIR = APP_DIR / "app-profile"
LOG_FILE = APP_DIR / "desktop.log"
_lock_handle = None


def _configure_logging() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    logging.info("Arati Hotel launcher starting (pid=%s)", os.getpid())


def _notify_error(message: str) -> None:
    logging.error(message)
    for command in (
        ["zenity", "--error", "--title=Arati Hotel", f"--text={message}"],
        ["notify-send", "-u", "critical", "Arati Hotel", message],
    ):
        if shutil.which(command[0]):
            try:
                subprocess.run(command, timeout=15, check=False)
                return
            except Exception:
                logging.exception("Could not show error dialog with %s", command[0])


def _acquire_instance_lock() -> bool:
    """Only one Arati Hotel server/window may own the database at a time."""
    global _lock_handle
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handle = (APP_DIR / "desktop.lock").open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    handle.write(str(os.getpid()))
    handle.flush()
    _lock_handle = handle
    return True


def _focus_existing() -> None:
    if shutil.which("wmctrl"):
        subprocess.run(
            ["wmctrl", "-a", "Arati Hotel"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )


def _ensure_database() -> None:
    """Make the shortcut self-healing after a reboot or a new install."""
    from sqlalchemy import select  # noqa: PLC0415

    from webapp.database import SessionLocal, engine  # noqa: PLC0415
    from webapp.main import upgrade_database  # noqa: PLC0415
    from webapp.models import CatalogItem, User  # noqa: PLC0415

    upgrade_database()
    with SessionLocal() as db:
        has_users = db.scalar(select(User.id).limit(1)) is not None
        has_menu = db.scalar(
            select(CatalogItem.id).where(CatalogItem.menu_group != "").limit(1)
        ) is not None

    if not has_users:
        logging.info("No users found — creating the initial hotel accounts")
        from webapp.seed import seed_demo_data  # noqa: PLC0415

        seed_demo_data()

    if not has_menu:
        logging.info("No restaurant menu found — creating the complete menu")
        from webapp.seed_menu import MENU as SEEDED_MENU  # noqa: PLC0415
        from webapp.seed_menu import seed_complete_menu  # noqa: PLC0415

        added = seed_complete_menu()
        logging.info("Menu ready: %s items seeded (%s new)", len(SEEDED_MENU), added)
    else:
        logging.info("Database ready")

    engine.dispose()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 30.0) -> None:
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


def _create_desktop_shortcut() -> None:
    """Create a .desktop file for the application menu."""
    try:
        desktop_dir = Path.home() / ".local" / "share" / "applications"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        
        desktop_file = desktop_dir / "arati-hotel.desktop"
        python_path = sys.executable
        script_path = Path(__file__).resolve()
        
        content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=Arati Hotel
Comment=Hotel Billing & Management System
Exec={python_path} {script_path}
Icon={ROOT / "webapp" / "static" / "icon.png" if (ROOT / "webapp" / "static" / "icon.png").exists() else "applications-office"}
Terminal=false
Categories=Office;Business;
StartupNotify=true
StartupWMClass=arati-hotel
"""
        desktop_file.write_text(content)
        desktop_file.chmod(0o755)
        logging.info("Desktop shortcut created at %s", desktop_file)
    except Exception as e:
        logging.warning("Could not create desktop shortcut: %s", e)


def main() -> int:
    _configure_logging()
    if not _acquire_instance_lock():
        logging.info("Arati Hotel is already running — focusing its window")
        _focus_existing()
        return 0

    _create_desktop_shortcut()

    server = None
    server_thread = None
    try:
        logging.info("Preparing database")
        _ensure_database()

        port_env = os.environ.get("ARATI_WEB_PORT")
        port = int(port_env) if port_env else _free_port()

        import uvicorn  # noqa: PLC0415

        from webapp.main import app  # noqa: PLC0415

        config = uvicorn.Config(app, host=HOST, port=port, log_level="error")
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        _wait_for_server(port)
        logging.info("Server ready at http://%s:%s", HOST, port)

        url = f"http://{HOST}:{port}"
        chrome_candidates = ["google-chrome", "chromium", "chromium-browser", "chrome"]
        chrome = next((c for c in chrome_candidates if shutil.which(c)), None)

        if chrome:
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            cmd = [
                chrome,
                "--app=" + url,
                "--user-data-dir=" + str(PROFILE_DIR),
                "--class=arati-hotel",
                "--window-size=1600,950",
                "--no-first-run",
                "--no-default-browser-check",
                "--name=Arati Hotel",
            ]
            logging.info("Opening app window with %s", chrome)
            proc = subprocess.Popen(cmd)
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
        else:
            import webbrowser  # noqa: PLC0415

            logging.warning("No app-capable browser found — opening default browser")
            webbrowser.open(url)
            print(f"No app-capable browser found — open {url} manually. Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        return 0
    except Exception as exc:
        logging.exception("Arati Hotel failed to start")
        _notify_error(
            "Arati Hotel could not start.\n\n"
            f"{exc}\n\n"
            f"Details: {LOG_FILE}"
        )
        return 1
    finally:
        print("Closing Arati Hotel...")
        logging.info("Closing Arati Hotel")
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=5)
        try:
            from webapp.database import engine  # noqa: PLC0415

            with engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            engine.dispose()
        except Exception:
            logging.exception("Database shutdown checkpoint failed")


if __name__ == "__main__":
    raise SystemExit(main())
