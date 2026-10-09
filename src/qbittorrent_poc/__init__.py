"""Proof-of-concept client for the qBittorrent WebUI API (v2.x, qBittorrent 5.x)."""

from . import fields, fmt, samples
from .client import QbtClient
from .config import Settings, connect
from .errors import QbtError
from .webui import FILTERS, TORRENT_FIELDS, TORRENT_STATES, WEBUI_SECURITY_PREFS, WebUI

__all__ = [
    "FILTERS",
    "TORRENT_FIELDS",
    "TORRENT_STATES",
    "WEBUI_SECURITY_PREFS",
    "QbtClient",
    "QbtError",
    "Settings",
    "WebUI",
    "connect",
    "fields",
    "fmt",
    "samples",
]
