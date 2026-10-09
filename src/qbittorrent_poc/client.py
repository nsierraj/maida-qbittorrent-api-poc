"""Minimal qBittorrent WebUI API client using an API key (qBittorrent >= 5.2).

Reference: docs/qbittorrent/webui-api.md

Every request carries `Authorization: Bearer <key>`, so there is no login, cookie or session
to refresh. The key never appears in repr(), errors or logs.
"""

from __future__ import annotations

from typing import Any

import requests

from .errors import QbtError

API_PREFIX = "/api/v2/"


def encode(value: Any) -> str:
    """Encode a form/query value the way qBittorrent expects: lowercase booleans."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _clean(params: dict[str, Any] | None) -> dict[str, str]:
    return {k: encode(v) for k, v in (params or {}).items() if v is not None}


class QbtClient:
    def __init__(
        self,
        host: str,
        port: int = 8090,
        *,
        api_key: str,
        scheme: str = "http",
        timeout: float = 30,
    ):
        if not api_key:
            raise ValueError("An API key is required (QBT_API_KEY, see README).")
        self.base_url = f"{scheme}://{host}:{port}"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def __repr__(self) -> str:
        return f"QbtClient({self.base_url!r})"

    def __enter__(self) -> QbtClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    def url(self, endpoint: str) -> str:
        return self.base_url + API_PREFIX + endpoint.lstrip("/")

    # -- calls -----------------------------------------------------------------
    def get(self, endpoint: str, **params: Any) -> Any:
        """GET /api/v2/<endpoint>. None-valued params are omitted."""
        return self._send("GET", endpoint, params=_clean(params))

    def post(self, endpoint: str, data: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        """POST form-encoded data to /api/v2/<endpoint>. Extra kwargs (e.g. files) go to requests."""
        return self._send("POST", endpoint, data=_clean(data), **kwargs)

    def _send(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        resp = self.session.request(method, self.url(endpoint), timeout=self.timeout, **kwargs)
        if resp.status_code >= 400:
            raise QbtError(endpoint, resp.status_code, resp.text)
        return self._decode(resp)

    @staticmethod
    def _decode(resp: requests.Response) -> Any:
        """JSON when the server says so, else the text body (e.g. version strings, 'Ok.')."""
        if resp.headers.get("Content-Type", "").startswith("application/json"):
            return resp.json()
        return resp.text
