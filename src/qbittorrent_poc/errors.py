"""Errors raised by the qBittorrent WebUI API client.

qBittorrent reports failures as HTTP status codes with a short text body (often empty).
The meanings below come from docs/qbittorrent/webui-api.md §1.
"""

from __future__ import annotations

STATUS_MEANINGS = {
    400: "Bad request: a parameter is missing or invalid",
    401: "Unauthorized: the API key was rejected, or the Host/Referer/Origin header failed validation",
    403: "Forbidden: the API key was rejected, the IP is banned, or there is no write access",
    404: "Not found: unknown torrent hash",
    405: "Method not allowed: this endpoint needs the other HTTP method (GET vs POST)",
    409: "Conflict: unknown category, name already in use, or invalid value",
    415: "Unsupported media type: invalid torrent file",
}


def describe(status: int) -> str:
    return STATUS_MEANINGS.get(status, "Unexpected HTTP status")


class QbtError(Exception):
    """A WebUI API call returned an error status."""

    def __init__(self, endpoint: str, status: int, body: str = ""):
        self.endpoint = endpoint
        self.status = status
        self.body = body.strip()[:200]
        self.message = describe(status)
        detail = f" (server said: {self.body!r})" if self.body else ""
        super().__init__(f"{endpoint} -> HTTP {status}: {self.message}{detail}")

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403)
