#!/usr/bin/env python3
"""Check the credentials the webapp and the KOT sync use.

Reads `.env` (or `--env-file`) and verifies, without printing any secret:

* the Render KOT cloud (`KOT_CLOUD_*`) answers and accepts the login;
* the hosted/local webapp (`ARATI_WEBSITE_ADMIN_*`) answers and accepts the
  browser login (form + CSRF, exactly like a person signing in).

Usage:
    python scripts/check_credentials.py
    python scripts/check_credentials.py --cloud
    python scripts/check_credentials.py --webapp --webapp-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = ROOT / ".env"
DEFAULT_CLOUD = "https://arati-kot.onrender.com"
DEFAULT_WEBAPP = "https://arati-webapp.onrender.com"
TIMEOUT = 75


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return 3xx responses instead of following them (login answers 303)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def fetch(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with (opener or urllib.request.build_opener()).open(
            request, timeout=TIMEOUT
        ) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, dict(response.headers), body
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        return error.code, dict(error.headers), body


def check_cloud(env: dict[str, str]) -> bool:
    base = (env.get("KOT_CLOUD_URL") or DEFAULT_CLOUD).rstrip("/")
    username = env.get("KOT_CLOUD_USERNAME", "")
    password = env.get("KOT_CLOUD_PASSWORD", "")
    print(f"\nKOT cloud: {base}")
    print(f"  username: {username or '(empty)'}  password: {mask(password)}")

    ok = True
    status, _, _ = fetch(f"{base}/api/health")
    print(f"  /api/health: {status}")
    ok &= status == 200

    if not username or not password:
        print("  login: SKIPPED (KOT_CLOUD_USERNAME/PASSWORD not set)")
        return False

    payload = json.dumps({"username": username, "password": password}).encode()
    status, _, body = fetch(
        f"{base}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    token = ""
    role = ""
    if status == 200:
        try:
            answer = json.loads(body)
            token = str(answer.get("access_token") or "")
            role = str(answer.get("role") or "")
        except json.JSONDecodeError:
            pass
    print(f"  login: {status}  role={role or '?'}  token={mask(token)}")
    ok &= status == 200 and bool(token)

    if token:
        status, _, body = fetch(
            f"{base}/api/tables",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        detail = ""
        try:
            rows = json.loads(body)
            if isinstance(rows, list):
                detail = f" ({len(rows)} tables)"
        except json.JSONDecodeError:
            detail = ""
        print(f"  authenticated call /api/tables: {status}{detail}")
        ok &= status == 200
    return ok


def check_webapp(env: dict[str, str], url: str) -> bool:
    url = url.rstrip("/")
    username = (
        env.get("ARATI_WEBSITE_ADMIN_USER")
        or env.get("ARATI_INITIAL_ADMIN_USER")
        or env.get("ARATI_WEBSITE_ADMIN_EMAIL", "")
    )
    password = env.get("ARATI_WEBSITE_ADMIN_PASSWORD") or env.get(
        "ARATI_INITIAL_ADMIN_PASSWORD", ""
    )
    print(f"\nWebapp: {url}")
    print(f"  username: {username or '(empty)'}  password: {mask(password)}")
    if username and "@" in username:
        print(
            "  note: this looks like an e-mail, but the webapp signs in with "
            "USERNAME only (no e-mail login)."
        )

    ok = True
    status, _, _ = fetch(f"{url}/healthz")
    print(f"  /healthz: {status}")
    ok &= status == 200

    if not username or not password:
        print("  login: SKIPPED (ARATI_WEBSITE_ADMIN_* not set)")
        return False

    jar = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), NoRedirect
    )
    status, _, html = fetch(f"{url}/login", opener=opener)
    print(f"  GET /login: {status}")
    ok &= status == 200
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if not match:
        print("  login: FAILED (no CSRF token on the login page)")
        return False

    form = urllib.parse.urlencode(
        {
            "csrf_token": match.group(1),
            "username": username,
            "password": password,
        }
    ).encode()
    status, headers, body = fetch(
        f"{url}/login",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        opener=opener,
    )
    location = headers.get("Location", "")
    # A successful form login answers 303 to /dashboard (or /password/change).
    success = status in (302, 303) and "/login" not in location
    reason = ""
    if not success:
        message = re.search(r'class="[^"]*alert[^"]*"[^>]*>(.*?)</', body, re.S)
        if message:
            reason = " ".join(re.sub(r"<[^>]+>", " ", message.group(1)).split())
    print(
        f"  POST /login: {status} -> {location or '-'}"
        f"{'  OK' if success else '  ' + (reason or 'rejected')}"
    )
    if success:
        status, _, _ = fetch(f"{url}/dashboard", opener=opener)
        print(f"  GET /dashboard: {status}")
        success &= status == 200
    return bool(ok and success)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--cloud", action="store_true", help="check KOT_CLOUD_*")
    parser.add_argument("--webapp", action="store_true", help="check the webapp login")
    parser.add_argument(
        "--webapp-url",
        default=None,
        help=f"webapp base URL (default: {DEFAULT_WEBAPP})",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="check the webapp running on localhost:8000 as well",
    )
    args = parser.parse_args()

    if not (args.cloud or args.webapp or args.local):
        args.cloud = args.webapp = True

    env = load_env(args.env_file)
    results: list[tuple[str, bool]] = []
    if args.cloud:
        results.append(("KOT cloud", check_cloud(env)))
    if args.webapp:
        results.append(
            ("Webapp", check_webapp(env, args.webapp_url or DEFAULT_WEBAPP))
        )
    if args.local:
        results.append(("Local webapp", check_webapp(env, "http://127.0.0.1:8000")))

    print("\nSummary")
    for name, ok in results:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
