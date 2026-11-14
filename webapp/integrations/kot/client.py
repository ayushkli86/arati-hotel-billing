# Copyright 2026 AI Memory System. All rights reserved.
"""HTTP client for the cloud KOT API.

Only outbound HTTPS: the local webapp talks to the hosted backend, never the
other way round. The client keeps one pooled connection, refreshes the token on
a 401, retries transient failures with exponential backoff and validates every
response shape before the sync engine sees it.

Secrets (password, bearer token) are never logged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .config import KotSyncSettings

_log = logging.getLogger("webapp.kot_sync")


class KotApiError(RuntimeError):
    """A cloud call failed in a way the caller should surface/retry."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _dict(payload: Any, what: str) -> dict:
    if not isinstance(payload, dict):
        raise KotApiError(f"{what}: expected an object, got {type(payload).__name__}")
    return payload


def _list(payload: Any, what: str) -> list:
    if not isinstance(payload, list):
        raise KotApiError(f"{what}: expected a list, got {type(payload).__name__}")
    return payload


class KotClient:
    """Thin, dependency-light wrapper over the KOT REST API."""

    retry_statuses = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(
        self,
        settings: KotSyncSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
    ) -> None:
        if not settings.base_url:
            raise KotApiError("KOT_CLOUD_URL is not set")
        self._settings = settings
        self._max_attempts = max(1, max_attempts)
        self._token = ""
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.request_timeout),
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": "arati-webapp-kot-sync/1.0"},
        )

    # ------------------------------------------------------------------ setup
    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "KotClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    # ------------------------------------------------------------------- auth
    async def _login(self) -> str:
        try:
            response = await self._client.post(
                "/api/auth/login",
                json={
                    "username": self._settings.username,
                    "password": self._settings.password,
                },
            )
        except httpx.HTTPError as exc:
            raise KotApiError(f"Cloud login failed: {type(exc).__name__}") from exc
        if response.status_code == 401:
            raise KotApiError(
                "Cloud login rejected: check KOT_CLOUD_USERNAME / KOT_CLOUD_PASSWORD",
                status=401,
            )
        if response.status_code >= 400:
            raise KotApiError(
                f"Cloud login failed ({response.status_code})", status=response.status_code
            )
        data = _dict(self._decode(response), "login")
        token = str(data.get("access_token") or "")
        if not token:
            raise KotApiError("Cloud login returned no access token")
        self._token = token
        _log.info("kot sync: authenticated as %s", self._settings.username)
        return token

    async def _auth_token(self, *, force: bool = False) -> str:
        if self._token and not force:
            return self._token
        async with self._lock:
            if self._token and not force:
                return self._token
            return await self._login()

    # --------------------------------------------------------------- requests
    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise KotApiError("Cloud response was not valid JSON") from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        auth: bool = True,
    ) -> Any:
        attempt = 0
        relogged = False
        while True:
            attempt += 1
            request_headers = dict(headers or {})
            if auth:
                request_headers["Authorization"] = f"Bearer {await self._auth_token()}"
            try:
                response = await self._client.request(
                    method, path, params=params, json=json, headers=request_headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._max_attempts:
                    raise KotApiError(f"{method} {path} failed: {type(exc).__name__}") from exc
                await self._sleep(attempt)
                continue

            if auth and response.status_code == 401 and not relogged:
                # Tokens expire; re-authenticate once and replay the request.
                relogged = True
                await self._auth_token(force=True)
                attempt -= 1
                continue

            if response.status_code in self.retry_statuses and attempt < self._max_attempts:
                _log.warning(
                    "kot sync: %s %s -> %s, retrying", method, path, response.status_code
                )
                await self._sleep(attempt)
                continue

            if response.status_code >= 400:
                detail = ""
                try:
                    body = self._decode(response)
                    if isinstance(body, dict):
                        detail = str(body.get("detail") or "")[:200]
                except KotApiError:
                    detail = ""
                raise KotApiError(
                    f"{method} {path} failed ({response.status_code})"
                    + (f": {detail}" if detail else ""),
                    status=response.status_code,
                )

            return self._decode(response)

    @staticmethod
    async def _sleep(attempt: int) -> None:
        # 0.5s, 1s, 2s … capped so a long outage never stalls a request for long.
        await asyncio.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))

    # ------------------------------------------------------------------- API
    async def health(self) -> dict:
        return _dict(await self._request("GET", "/api/health", auth=False), "health")

    async def list_kots(self, *, since_id: int = 0, limit: int = 100) -> list[dict]:
        rows = await self._request(
            "GET", "/api/kots", params={"since_id": int(since_id), "limit": int(limit)}
        )
        return [_dict(row, "kot") for row in _list(rows, "kots")]

    async def get_kot(self, kot_id: int) -> dict:
        return _dict(await self._request("GET", f"/api/kots/{int(kot_id)}"), "kot")

    async def create_kot(self, payload: dict, *, idempotency_key: str) -> dict:
        return _dict(
            await self._request(
                "POST", "/api/kots", json=payload,
                headers={"Idempotency-Key": idempotency_key[:64]},
            ),
            "kot",
        )

    async def list_tables(self) -> list[dict]:
        return [_dict(row, "table") for row in _list(
            await self._request("GET", "/api/tables"), "tables"
        )]

    async def list_dishes(self) -> list[dict]:
        return [_dict(row, "dish") for row in _list(
            await self._request("GET", "/api/dishes"), "dishes"
        )]

    async def create_dish(self, payload: dict) -> dict:
        return _dict(await self._request("POST", "/api/dishes", json=payload), "dish")

    async def update_dish(self, dish_id: int, payload: dict) -> dict:
        return _dict(
            await self._request("PATCH", f"/api/dishes/{int(dish_id)}", json=payload),
            "dish",
        )

    async def create_table(self, payload: dict) -> dict:
        return _dict(await self._request("POST", "/api/tables", json=payload), "table")

    async def update_table(self, table_id: int, payload: dict) -> dict:
        return _dict(
            await self._request("PATCH", f"/api/tables/{int(table_id)}", json=payload),
            "table",
        )
