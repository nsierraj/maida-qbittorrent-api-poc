"""In-memory stand-in for the qBittorrent 5.x WebUI API, patched into requests.Session.request.

It models the documented behavior (docs/qbittorrent/webui-api.md) plus qBittorrent's request
checks as implemented in its source (webapplication.cpp):

- API key auth: `Authorization: Bearer <key>`; anything else gets 403 "Forbidden".
- Host header validation: IP literals and localhost pass; other names must be in
  `server_domains`, else 401 "Unauthorized".
- CSRF protection: a Referer or Origin whose host:port differs from Host gets 401.
  Whether this applies to API key requests on the real server is probed by
  examples/00_probe_auth.py; `csrf_with_api_key` models either answer.
- Wrong HTTP method gets 405. Version strings come back as text/plain.

Filter semantics (downloading, seeding, active, ...) approximate qBittorrent's TorrentFilter.
Field names and state strings must match what examples/01_discover.py records from the real
server; when they differ, the real server wins and this file follows.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

import requests

from qbittorrent_poc.webui import TORRENT_FIELDS

API_KEY = "qbt_fakekeyfakekeyfakekey"
HOST = "192.0.2.10"  # TEST-NET-1, never a real NAS
PORT = 8090

DOWNLOADING = {"downloading", "metaDL", "forcedMetaDL", "stalledDL", "checkingDL", "stoppedDL",
               "queuedDL", "forcedDL"}
UPLOADING = {"uploading", "stalledUP", "checkingUP", "queuedUP", "forcedUP"}
STOPPED = {"stoppedDL", "stoppedUP"}
ACTIVE = {"downloading", "forcedDL", "metaDL", "forcedMetaDL", "uploading", "forcedUP", "moving"}
ERRORED = {"error", "missingFiles"}


def make_torrent(name: str, state: str, *, n: int, size: int = 4_000_000_000, progress: float = 1.0,
                 category: str = "", tags: str = "", dlspeed: int = 0, upspeed: int = 0) -> dict[str, Any]:
    h = f"{n:02x}" * 20
    done = int(size * progress)
    t: dict[str, Any] = {f: 0 for f in TORRENT_FIELDS}
    t.update(
        name=name, hash=h, state=state, size=size, total_size=size, progress=progress,
        completed=done, downloaded=done, amount_left=size - done, category=category, tags=tags,
        dlspeed=dlspeed, upspeed=upspeed, save_path="/data/torrents/linux",
        content_path=f"/data/torrents/linux/{name}", magnet_uri=f"magnet:?xt=urn:btih:{h}",
        tracker="", added_on=1_790_000_000 + n, dl_limit=-1, up_limit=-1, max_ratio=-1,
        max_seeding_time=-1, ratio_limit=-2, seeding_time_limit=-2, eta=8_640_000,
        availability=-1.0, ratio=0.0, auto_tmm=False, f_l_piece_prio=False, force_start=False,
        isPrivate=False, seq_dl=False, super_seeding=False, priority=0 if progress >= 1 else n,
    )
    return t


def default_torrents() -> list[dict[str, Any]]:
    return [
        make_torrent("ubuntu-26.04-desktop-amd64.iso", "downloading", n=1, progress=0.42,
                     category="linux", dlspeed=2_500_000, upspeed=40_000),
        make_torrent("debian-13.1.0-amd64-netinst.iso", "stoppedDL", n=2, size=700_000_000,
                     progress=0.1, category="linux"),
        make_torrent("archlinux-2026.10.01-x86_64.iso", "uploading", n=3, size=1_300_000_000,
                     category="linux", tags="keep, seed", upspeed=120_000),
        make_torrent("fedora-workstation-45.iso", "stoppedUP", n=4, size=2_400_000_000,
                     tags="keep"),
        make_torrent("big-buck-bunny-1080p.mkv", "stalledUP", n=5, size=900_000_000,
                     category="video"),
    ]


def _is_ip_or_localhost(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _response(status: int, body: Any = "", ctype: str | None = None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    if isinstance(body, (dict, list)):
        r._content = json.dumps(body).encode()
        r.headers["Content-Type"] = "application/json"
    else:
        r._content = str(body).encode()
        r.headers["Content-Type"] = ctype or "text/plain; charset=UTF-8"
    r.encoding = "utf-8"
    return r


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


class FakeQbt:
    def __init__(self) -> None:
        self.api_key = API_KEY
        self.version = "v5.2.3"
        self.webapi = "2.15.1"
        self.server_domains: set[str] = set()
        self.csrf_with_api_key = True
        self.torrents: list[dict[str, Any]] = default_torrents()
        self.categories: dict[str, dict[str, Any]] = {
            "linux": {"name": "linux", "savePath": "/data/torrents/linux"},
            "video": {"name": "video", "savePath": "/data/torrents/video"},
        }
        self.tags: list[str] = ["keep", "seed"]
        self.alt_speed = False
        self.requests: list[tuple[str, str, dict[str, Any]]] = []  # (method, endpoint, params/data)
        self.routes = {
            "app/version": ("GET", lambda p: _response(200, self.version)),
            "app/webapiVersion": ("GET", lambda p: _response(200, self.webapi)),
            "app/buildInfo": ("GET", lambda p: _response(200, {
                "qt": "6.9.2", "libtorrent": "2.0.11.0", "boost": "1.89.0", "openssl": "3.5.4",
                "zlib": "1.3.1", "bitness": 64, "platform": "linux"})),
            "app/defaultSavePath": ("GET", lambda p: _response(200, "/data/torrents")),
            "transfer/info": ("GET", self._transfer_info),
            "transfer/speedLimitsMode": ("GET", lambda p: _response(200, "1" if self.alt_speed else "0")),
            "torrents/info": ("GET", self._torrents_info),
            "torrents/categories": ("GET", lambda p: _response(200, self.categories)),
            "torrents/tags": ("GET", lambda p: _response(200, self.tags)),
            "auth/login": ("POST", lambda p: _response(200, "Fails.")),
        }

    # -- plumbing -------------------------------------------------------------------
    def install(self, monkeypatch: Any) -> None:
        fake = self

        def request(session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
            headers = {**session.headers, **(kwargs.get("headers") or {})}
            return fake.handle(method.upper(), url, headers, kwargs.get("params") or kwargs.get("data") or {})

        monkeypatch.setattr(requests.Session, "request", request)

    def handle(self, method: str, url: str, headers: dict[str, str], params: dict[str, Any]) -> requests.Response:
        parts = urlsplit(url)
        host_header = headers.get("Host") or parts.netloc
        hostname = host_header.rsplit(":", 1)[0] if not host_header.startswith("[") else host_header
        if not _is_ip_or_localhost(hostname) and hostname not in self.server_domains:
            return _response(401, "Unauthorized")
        auth = headers.get("Authorization", "")
        has_key = auth == f"Bearer {self.api_key}"
        if self.csrf_with_api_key or not has_key:
            for h in ("Origin", "Referer"):
                if headers.get(h) and urlsplit(headers[h]).netloc != host_header:
                    return _response(401, "Unauthorized")
        endpoint = parts.path.removeprefix("/api/v2/")
        if endpoint != "auth/login" and not has_key:
            return _response(403, "Forbidden")
        route = self.routes.get(endpoint)
        if route is None:
            return _response(404, "Not Found")
        allowed, handler = route
        if method != allowed:
            return _response(405, "Method Not Allowed")
        self.requests.append((method, endpoint, dict(params)))
        return handler(params)

    # -- handlers ---------------------------------------------------------------------
    def _transfer_info(self, p: dict[str, Any]) -> requests.Response:
        return _response(200, {
            "connection_status": "connected", "dht_nodes": 312,
            "dl_info_data": 51_000_000_000, "dl_info_speed": sum(t["dlspeed"] for t in self.torrents),
            "dl_rate_limit": 0, "up_info_data": 9_000_000_000,
            "up_info_speed": sum(t["upspeed"] for t in self.torrents), "up_rate_limit": 0,
        })

    @staticmethod
    def _matches(t: dict[str, Any], flt: str) -> bool:
        s = t["state"]
        return {
            "all": True,
            "downloading": s in DOWNLOADING,
            "seeding": s in UPLOADING,
            "completed": t["progress"] >= 1,
            "stopped": s in STOPPED,
            "running": s not in STOPPED,
            "active": s in ACTIVE or (s == "stalledDL" and t["upspeed"] > 0),
            "inactive": not (s in ACTIVE or (s == "stalledDL" and t["upspeed"] > 0)),
            "stalled": s in ("stalledUP", "stalledDL"),
            "stalled_uploading": s == "stalledUP",
            "stalled_downloading": s == "stalledDL",
            "errored": s in ERRORED,
        }[flt]

    def _torrents_info(self, p: dict[str, Any]) -> requests.Response:
        flt = p.get("filter", "all")
        items = [t for t in self.torrents if self._matches(t, flt)] if flt in (
            "all", "downloading", "seeding", "completed", "stopped", "running", "active", "inactive",
            "stalled", "stalled_uploading", "stalled_downloading", "errored") else list(self.torrents)
        if "category" in p:
            items = [t for t in items if t["category"] == p["category"]]
        if "tag" in p:
            want = p["tag"]
            items = [t for t in items if (want in [x.strip() for x in t["tags"].split(",") if x.strip()])
                     or (want == "" and not t["tags"])]
        if "hashes" in p and p["hashes"] != "all":
            wanted = set(p["hashes"].split("|"))
            items = [t for t in items if t["hash"] in wanted]
        if p.get("sort"):
            items.sort(key=lambda t: t.get(p["sort"], 0), reverse=_truthy(p.get("reverse")))
        offset = int(p.get("offset", 0))
        if offset < 0:
            offset = max(len(items) + offset, 0)
        items = items[offset:]
        if "limit" in p and int(p["limit"]) > 0:
            items = items[: int(p["limit"])]
        return _response(200, items)
