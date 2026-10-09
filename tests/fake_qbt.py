"""In-memory stand-in for the qBittorrent 5.x WebUI API, patched into requests.Session.request.

It models the behavior observed on the real server (qBittorrent 5.2.3, WebAPI 2.15.1, probed
2026-10-09 with examples/00_probe_auth.py and 01_discover.py; see webui-api.md §8):

- API key auth: `Authorization: Bearer <key>`; a missing or wrong key gets 403 "Forbidden".
- API key requests skip the CSRF check: a foreign Referer or Origin still gets 200.
  Cookie-style requests (no key) with a foreign Referer/Origin get 401 (`csrf_with_api_key`
  turns the check on for key requests too).
- A container name in Host (`gluetun:8090`) was accepted. With `host_header_validation=True`
  the fake instead refuses names that aren't IPs, localhost or in `server_domains` (401).
- GET-only endpoints also accept POST. POST-only endpoints refuse GET with 405 (per
  qBittorrent's source; to be confirmed on the real server in Stage 3).
- Stage 2 endpoints (properties, files, trackers, peers, maindata, log) follow the wiki or
  qBittorrent's source and are unverified until examples/02_inspect.py runs on the real server.
  Unknown hashes get 404. sync/maindata and sync/torrentPeers return deltas when given the rid
  of an earlier response, and everything when the rid is 0 or unknown.
- Stage 3 writes are POST-only (GET gets 405). torrents/add reads `stopped` (5.x) or `paused`
  (4.x) and answers JSON `{added_torrent_ids, success_count, pending_count, failure_count}` as
  5.2.3 does (URL adds count as pending; `legacy_add_answer` switches to the wiki's "Ok."/"Fails.").
  The torrent appears in torrents/info at once, shows `checkingResumeData` on the first read (as
  observed), then its requested state; a magnet without metadata sits in metaDL/stoppedDL with size 0 until
  `fetch_metadata()` is called. URLs of .torrent files are fetched from `web` (the fake
  "internet", which also serves the examples' own downloads); an unknown URL still answers
  "Ok." and nothing appears, as a failed background download would. delete answers 200 even for unknown hashes. Unverified until
  examples/03_lifecycle.py runs on the real server.
- Version strings come back as text/plain. torrents/info sends `private`, not the wiki's
  `isPrivate`, plus 20 fields the wiki doesn't list; limits use 0 for unlimited.

Filter semantics (downloading, seeding, active, ...) approximate qBittorrent's TorrentFilter.
Field names and state strings must match what examples/01_discover.py records from the real
server; when they differ, the real server wins and this file follows.
"""

from __future__ import annotations

import copy
import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

import requests

from qbittorrent_poc import torrentfile
from qbittorrent_poc.fields import TORRENT_FIELDS

API_KEY = "qbt_fakekeyfakekeyfakekey"

# A stand-in for the Arch ISO .torrent the lifecycle example adds by default, served by the fake
# "internet" in FakeQbt.web (same name, size and piece length as the real one; fake piece hashes).
ARCH_URL = "https://fastly.mirror.pkgbuild.com/iso/2026.10.01/archlinux-2026.10.01-x86_64.iso.torrent"
ARCH_SIZE = 1_640_497_152
ARCH_TORRENT = torrentfile.encode({
    "comment": "Arch Linux 2026.10.01 <https://archlinux.org>",
    "created by": "mktorrent 1.1",
    "info": {"length": ARCH_SIZE, "name": "archlinux-2026.10.01-x86_64.iso",
             "piece length": 524_288, "pieces": b"\x01" * 20 * (-(-ARCH_SIZE // 524_288))},
    "url-list": ["https://mirror.example.org/archlinux/iso/2026.10.01/"],
})
ARCH_HASH = torrentfile.parse(ARCH_TORRENT).info_hash
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
    """A torrents/info row with every field the real server sends and its observed defaults."""
    h = f"{n:02x}" * 20
    done = int(size * progress)
    piece = 4_194_304
    pieces = -(-size // piece)
    t: dict[str, Any] = {f: 0 for f in TORRENT_FIELDS}
    t.update(
        name=name, hash=h, infohash_v1=h, infohash_v2="", state=state, size=size, total_size=size,
        progress=progress, completed=done, downloaded=done, downloaded_session=done,
        amount_left=size - done, category=category, tags=tags, dlspeed=dlspeed, upspeed=upspeed,
        save_path="/data/torrents/linux", download_path="", root_path="",
        content_path=f"/data/torrents/linux/{name}", magnet_uri=f"magnet:?xt=urn:btih:{h}",
        tracker="", trackers_count=1, comment="", created_by="", creation_date=-1,
        added_on=1_790_000_000 + n, completion_on=1_790_000_500 + n if progress >= 1 else -1,
        dl_limit=0, up_limit=0, max_ratio=0, max_seeding_time=-1, max_inactive_seeding_time=-1,
        ratio_limit=-2, seeding_time_limit=-2, inactive_seeding_time_limit=-2,
        share_limit_action="Default", eta=8_640_000, availability=-1, ratio=0.0, popularity=0.0,
        connections_limit=100, piece_size=piece, pieces_num=pieces,
        pieces_have=pieces if progress >= 1 else int(pieces * progress), has_metadata=True,
        auto_tmm=False, f_l_piece_prio=False, force_start=False, private=False, seq_dl=False,
        super_seeding=False, priority=0 if progress >= 1 else n,
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


def category(name: str, save_path: str) -> dict[str, Any]:
    """A torrents/categories value in the shape the real server sends."""
    return {"name": name, "savePath": save_path, "download_path": None, "ratio_limit": -2,
            "seeding_time_limit": -2, "inactive_seeding_time_limit": -2,
            "share_limit_action": "Default"}


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
    r._content_consumed = True  # lets iter_content()/streaming read the body
    return r


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


class FakeQbt:
    def __init__(self) -> None:
        self.api_key = API_KEY
        self.version = "v5.2.3"
        self.webapi = "2.15.1"
        self.server_domains: set[str] = set()
        self.host_header_validation = False  # observed: "gluetun:8090" accepted
        self.csrf_with_api_key = False  # observed: key requests skip the Referer/Origin check
        self.torrents: list[dict[str, Any]] = default_torrents()
        self.categories: dict[str, dict[str, Any]] = {
            "linux": category("linux", "/data/torrents/linux"),
            "video": category("video", ""),  # "" = the default save path (seen on the real server)
        }
        self.preferences: dict[str, Any] = {
            "web_ui_port": PORT, "web_ui_host_header_validation_enabled": False,
            "web_ui_domain_list": "*", "web_ui_csrf_protection_enabled": True,
            "web_ui_clickjacking_protection_enabled": True, "bypass_local_auth": False,
            "bypass_auth_subnet_whitelist_enabled": False, "web_ui_max_auth_fail_count": 5,
            "web_ui_ban_duration": 3600, "web_ui_session_timeout": 3600, "use_https": False,
            "web_ui_reverse_proxy_enabled": False, "auto_tmm_enabled": False,
            # "Keep incomplete torrents in", as on the real NAS.
            "temp_path_enabled": True, "temp_path": "/data/torrents/incoming",
            # Secrets live here too; the library must never return them.
            "web_ui_password": "fake-password-hash", "proxy_password": "fake-proxy-secret",
        }
        self.tags: list[str] = ["keep", "seed"]
        self.alt_speed = False
        self.free_space = 1_200_000_000_000
        self.log: list[dict[str, Any]] = [
            {"id": 0, "type": 1, "timestamp": 1_790_000_000, "message": "qBittorrent v5.2.3 started"},
            {"id": 1, "type": 2, "timestamp": 1_790_000_001, "message": "Using config directory: /config/qBittorrent"},
            {"id": 2, "type": 2, "timestamp": 1_790_000_002, "message": "Trying to listen on: 0.0.0.0:6881"},
            {"id": 3, "type": 4, "timestamp": 1_790_000_100, "message": "Tracker error: timed out. Torrent: debian"},
            {"id": 4, "type": 8, "timestamp": 1_790_000_200, "message": "File error alert. Reason: disk full"},
        ]
        self.rechecked: list[str] = []
        self.recheck_resumes = False
        self.add_settles_through: str | None = "checkingResumeData"  # observed on 5.2.3
        self.legacy_add_answer = False  # True: the wiki's "Ok."/"Fails." text instead of 5.2.3's JSON
        self.deleted_files: list[str] = []
        self.web: dict[str, bytes | str] = {ARCH_URL: ARCH_TORRENT}  # the "internet"; str = redirect
        self.downloads: list[str] = []  # every non-API URL fetched  # hashes deleted with deleteFiles=true
        self._rid = 0
        self._sync_snapshots: dict[int, dict[str, Any]] = {}
        self._peer_snapshots: dict[tuple[str, int], dict[str, Any]] = {}
        self.requests: list[tuple[str, str, dict[str, Any]]] = []  # (method, endpoint, params/data)
        self.routes = {
            "app/version": ("GET", lambda p: _response(200, self.version)),
            "app/webapiVersion": ("GET", lambda p: _response(200, self.webapi)),
            "app/buildInfo": ("GET", lambda p: _response(200, {
                "qt": "6.9.2", "libtorrent": "2.0.11.0", "boost": "1.89.0", "openssl": "3.5.4",
                "zlib": "1.3.1", "bitness": 64, "platform": "linux"})),
            "app/defaultSavePath": ("GET", lambda p: _response(200, "/data/torrents/completed")),
            "app/preferences": ("GET", lambda p: _response(200, self.preferences)),
            "transfer/info": ("GET", self._transfer_info),
            "transfer/speedLimitsMode": ("GET", lambda p: _response(200, "1" if self.alt_speed else "0")),
            "torrents/info": ("GET", self._torrents_info),
            "torrents/categories": ("GET", lambda p: _response(200, self.categories)),
            "torrents/tags": ("GET", lambda p: _response(200, self.tags)),
            "torrents/properties": ("GET", self._with_torrent(self._properties)),
            "torrents/files": ("GET", self._with_torrent(self._files)),
            "torrents/trackers": ("GET", self._with_torrent(self._trackers)),
            "torrents/webseeds": ("GET", self._with_torrent(lambda t, p: [])),
            "sync/torrentPeers": ("GET", self._with_torrent(self._torrent_peers)),
            "sync/maindata": ("GET", self._maindata),
            "log/main": ("GET", self._main_log),
            "torrents/add": ("POST", self._add),
            "torrents/stop": ("POST", self._for_hashes(self._stop)),
            "torrents/start": ("POST", self._for_hashes(self._start)),
            "torrents/recheck": ("POST", self._for_hashes(self._recheck)),
            "torrents/reannounce": ("POST", self._for_hashes(lambda t, p: None)),
            "torrents/setCategory": ("POST", self._set_category),
            "torrents/createCategory": ("POST", self._create_category),
            "torrents/removeCategories": ("POST", self._remove_categories),
            "torrents/addTags": ("POST", self._for_hashes(self._add_tags)),
            "torrents/removeTags": ("POST", self._for_hashes(self._remove_tags)),
            "torrents/deleteTags": ("POST", self._delete_tags),
            "torrents/rename": ("POST", self._rename),
            "torrents/setLocation": ("POST", self._set_location),
            "torrents/delete": ("POST", self._delete),
            "auth/login": ("POST", lambda p: _response(200, "Fails.")),
        }

    # -- plumbing -------------------------------------------------------------------
    def install(self, monkeypatch: Any) -> None:
        fake = self

        def request(session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
            headers = {**session.headers, **(kwargs.get("headers") or {})}
            params = dict(kwargs.get("params") or kwargs.get("data") or {})
            files = kwargs.get("files")
            if isinstance(files, list):  # torrents/add uploads: [("torrents", (name, bytes, type)), ...]
                params["_files"] = [part[1][1] for part in files if part[0] == "torrents"]
            return fake.handle(method.upper(), url, headers, params)

        monkeypatch.setattr(requests.Session, "request", request)

    def handle(self, method: str, url: str, headers: dict[str, str], params: dict[str, Any]) -> requests.Response:
        parts = urlsplit(url)
        if not parts.path.startswith("/api/v2/"):  # a plain download, e.g. a .torrent file
            self.downloads.append(url)
            body = self.web.get(url)
            if body is None:
                return _response(404, "Not Found")
            if isinstance(body, str):  # a redirect to that URL
                r = _response(302, "")
                r.headers["Location"] = body
                return r
            r = _response(200, "")
            r._content = body
            r.headers["Content-Type"] = "application/x-bittorrent"
            return r
        host_header = headers.get("Host") or parts.netloc
        hostname = host_header.rsplit(":", 1)[0] if not host_header.startswith("[") else host_header
        if (self.host_header_validation and not _is_ip_or_localhost(hostname)
                and hostname not in self.server_domains):
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
        if allowed == "POST" and method != "POST":  # GET-only endpoints also accept POST
            return _response(405, "Method Not Allowed")
        self.requests.append((method, endpoint, dict(params)))
        return handler(params)

    # -- handlers ---------------------------------------------------------------------
    def _transfer_info(self, p: dict[str, Any]) -> requests.Response:
        return _response(200, {
            "connection_status": "connected", "dht_nodes": 312,
            "last_external_address_v4": "203.0.113.7", "last_external_address_v6": "",
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

    def _settle(self) -> None:
        """A just-added torrent shows its transient state once, then the requested one."""
        for t in self.torrents:
            if "_settle" in t:
                if t.get("_seen"):
                    t["state"] = t.pop("_settle")
                    t.pop("_seen")
                else:
                    t["_seen"] = True

    def _torrents_info(self, p: dict[str, Any]) -> requests.Response:
        self._settle()
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
        return _response(200, [{k: v for k, v in t.items() if not k.startswith("_")} for t in items])

    # -- Stage 2: per-torrent detail ------------------------------------------------------
    def torrent(self, torrent_hash: str) -> dict[str, Any] | None:
        return next((t for t in self.torrents if t["hash"] == torrent_hash), None)

    def _with_torrent(self, handler: Any) -> Any:
        def wrapped(p: dict[str, Any]) -> requests.Response:
            t = self.torrent(p.get("hash", ""))
            if t is None:
                return _response(404, "Not Found")
            return _response(200, handler(t, p))
        return wrapped

    @staticmethod
    def _properties(t: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
        return {
            "save_path": t["save_path"], "creation_date": t["creation_date"], "piece_size": t["piece_size"],
            "comment": t["comment"], "total_wasted": t["total_wasted"], "total_uploaded": t["uploaded"],
            "total_uploaded_session": t["uploaded_session"], "total_downloaded": t["downloaded"],
            "total_downloaded_session": t["downloaded_session"], "up_limit": t["up_limit"],
            "dl_limit": t["dl_limit"], "time_elapsed": t["time_active"], "seeding_time": t["seeding_time"],
            "nb_connections": t["connections_count"], "nb_connections_limit": t["connections_limit"],
            "share_ratio": t["ratio"], "addition_date": t["added_on"], "completion_date": t["completion_on"],
            "created_by": t["created_by"], "dl_speed_avg": t["dlspeed"], "dl_speed": t["dlspeed"],
            "eta": t["eta"], "last_seen": t["seen_complete"], "peers": t["num_leechs"],
            "peers_total": t["num_incomplete"], "pieces_have": t["pieces_have"], "pieces_num": t["pieces_num"],
            "reannounce": t["reannounce"], "seeds": t["num_seeds"], "seeds_total": t["num_complete"],
            "total_size": t["total_size"], "up_speed_avg": t["upspeed"], "up_speed": t["upspeed"],
            "private": t["private"], "is_private": t["private"], "hash": t["hash"], "name": t["name"],
            "infohash_v1": t["infohash_v1"], "infohash_v2": t["infohash_v2"], "progress": t["progress"],
            "availability": t["availability"], "popularity": t["popularity"],
            "has_metadata": t["has_metadata"], "download_path": t["download_path"],
        }

    @staticmethod
    def _files(t: dict[str, Any], p: dict[str, Any]) -> list[dict[str, Any]]:
        last_piece = t["pieces_num"] - 1
        if t["name"].endswith(".mkv"):  # a multi-file torrent: folder with video, subtitles, an nfo
            folder = t["name"].removesuffix(".mkv")
            parts = [(f"{folder}/{t['name']}", t["size"] - 60_000, 1), (f"{folder}/{folder}.en.srt", 50_000, 1),
                     (f"{folder}/{folder}.nfo", 10_000, 0)]
        else:
            parts = [(t["name"], t["size"], 1)]
        rows = []
        for i, (name, size, prio) in enumerate(parts):
            rows.append({"index": i, "name": name, "size": size, "priority": prio,
                         "progress": t["progress"] if prio else 0.0, "is_seed": t["progress"] >= 1,
                         "piece_range": [0, last_piece], "availability": 1.0})
        wanted = p.get("indexes")
        if wanted:
            keep = {int(x) for x in wanted.split("|")}
            rows = [r for r in rows if r["index"] in keep]
        return rows

    @staticmethod
    def _trackers(t: dict[str, Any], p: dict[str, Any]) -> list[dict[str, Any]]:
        pseudo = [{"url": f"** [{name}] **", "status": 2, "tier": -1,
                   "num_peers": 0, "num_seeds": 0, "num_leeches": 0, "num_downloaded": 0, "msg": ""}
                  for name in ("DHT", "PeX", "LSD")]
        real = [
            {"url": "https://tracker.example.org/announce", "status": 2, "tier": 0, "num_peers": 40,
             "num_seeds": 31, "num_leeches": 9, "num_downloaded": 1200, "msg": ""},
            {"url": "udp://tracker.example.net:1337/announce", "status": 4, "tier": 1, "num_peers": -1,
             "num_seeds": -1, "num_leeches": -1, "num_downloaded": -1, "msg": "timed out"},
        ]
        return pseudo + real

    def _peer_rows(self, t: dict[str, Any]) -> dict[str, Any]:
        if t["state"] in ("stoppedDL", "stoppedUP"):
            return {}
        n = int(t["hash"][:2], 16)
        return {
            f"198.51.100.{n}:51413": {
                "client": "qBittorrent/5.1.2", "connection": "BT", "country": "Netherlands",
                "country_code": "nl", "dl_speed": t["dlspeed"], "downloaded": 1_000_000, "files": "",
                "flags": "D X E P", "flags_desc": "D = Currently downloading", "ip": f"198.51.100.{n}",
                "host_name": f"host-{n}.peers.example.net",
                "peer_id_client": "-qB5120-", "port": 51413, "progress": 1.0, "relevance": 1.0,
                "up_speed": t["upspeed"], "uploaded": 20_000},
            f"198.51.100.{n + 100}:6881": {
                "client": "Transmission 4.0.6", "connection": "μTP", "country": "Canada",
                "country_code": "ca", "dl_speed": 0, "downloaded": 0, "files": "", "flags": "u I",
                "flags_desc": "u = Peer wants data", "ip": f"198.51.100.{n + 100}", "host_name": "",
                "peer_id_client": "-TR4060-", "port": 6881, "progress": 0.3, "relevance": 0.0,
                "up_speed": 0, "uploaded": 0},
        }

    def _next_rid(self) -> int:
        self._rid += 1
        return self._rid

    def _torrent_peers(self, t: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
        peers = self._peer_rows(t)
        rid = int(p.get("rid") or 0)
        old = self._peer_snapshots.get((t["hash"], rid))
        new_rid = self._next_rid()
        self._peer_snapshots[(t["hash"], new_rid)] = copy.deepcopy(peers)
        if old is None:
            return {"full_update": True, "peers": peers, "rid": new_rid, "show_flags": True}
        body: dict[str, Any] = {"rid": new_rid, "show_flags": True,
                                "peers": {k: _changed(old.get(k, {}), v) for k, v in peers.items()
                                          if old.get(k) != v}}
        removed = sorted(set(old) - set(peers))
        if removed:
            body["peers_removed"] = removed
        return body

    def server_state(self) -> dict[str, Any]:
        info = json.loads(self._transfer_info({}).content)
        info.update(
            alltime_dl=900_000_000_000, alltime_ul=120_000_000_000, average_time_queue=0,
            free_space_on_disk=self.free_space, global_ratio="0.13", queued_io_jobs=0,
            queueing=False, read_cache_hits="0", read_cache_overload="0", refresh_interval=1500,
            total_buffers_size=0, total_peer_connections=sum(len(self._peer_rows(t)) for t in self.torrents),
            total_queued_size=0, total_wasted_session=0, use_alt_speed_limits=self.alt_speed,
            write_cache_overload="0",
        )
        return info

    def _sync_state(self) -> dict[str, Any]:
        flags = {"has_tracker_error": False, "has_tracker_warning": False, "has_other_announce_error": False}
        return {"torrents": {t["hash"]: {**{k: v for k, v in t.items() if k != "hash" and not k.startswith("_")},
                                         **flags} for t in self.torrents},
                "categories": copy.deepcopy(self.categories), "tags": list(self.tags),
                "server_state": self.server_state()}

    def _maindata(self, p: dict[str, Any]) -> requests.Response:
        state = self._sync_state()
        rid = int(p.get("rid") or 0)
        old = self._sync_snapshots.get(rid)
        new_rid = self._next_rid()
        self._sync_snapshots[new_rid] = copy.deepcopy(state)
        if old is None:
            return _response(200, {"rid": new_rid, "full_update": True, **state})
        body: dict[str, Any] = {"rid": new_rid}
        torrents = {h: _changed(old["torrents"].get(h, {}), row) for h, row in state["torrents"].items()
                    if old["torrents"].get(h) != row}
        if torrents:
            body["torrents"] = torrents
        removed = sorted(set(old["torrents"]) - set(state["torrents"]))
        if removed:
            body["torrents_removed"] = removed
        cats = {k: v for k, v in state["categories"].items() if old["categories"].get(k) != v}
        if cats:
            body["categories"] = cats
        if gone := sorted(set(old["categories"]) - set(state["categories"])):
            body["categories_removed"] = gone
        if added := [t for t in state["tags"] if t not in old["tags"]]:
            body["tags"] = added
        if dropped := [t for t in old["tags"] if t not in state["tags"]]:
            body["tags_removed"] = dropped
        if server := _changed(old["server_state"], state["server_state"]):
            body["server_state"] = server
        return _response(200, body)

    def _main_log(self, p: dict[str, Any]) -> requests.Response:
        wanted = {bit for name, bit in (("normal", 1), ("info", 2), ("warning", 4), ("critical", 8))
                  if p.get(name, "true").lower() != "false"}
        after = int(p.get("last_known_id", -1))
        return _response(200, [e for e in self.log if e["type"] in wanted and e["id"] > after])

    def add_log(self, message: str, type_: int = 2) -> None:
        self.log.append({"id": len(self.log), "type": type_, "timestamp": 1_790_001_000 + len(self.log),
                         "message": message})


    # -- Stage 3: changes ------------------------------------------------------------------------
    def _for_hashes(self, handler: Any) -> Any:
        """Apply handler(torrent, params) to every torrent named in `hashes` ('all' = every one).
        Unknown hashes are ignored, as the server does."""
        def wrapped(p: dict[str, Any]) -> requests.Response:
            wanted = p.get("hashes", "")
            if not wanted:
                return _response(400, "")
            targets = self.torrents if wanted == "all" else [
                t for t in self.torrents if t["hash"] in wanted.lower().split("|")]
            for t in targets:
                if "_settle" in t:  # a command during the transient check applies to the real state
                    t["state"] = t.pop("_settle")
                    t.pop("_seen", None)
                handler(t, p)
            return _response(200, "")
        return wrapped

    def _add(self, p: dict[str, Any]) -> requests.Response:
        from qbittorrent_poc.webui import magnet_hash

        urls = [u for u in p.get("urls", "").split("\n") if u.strip()]
        uploads = p.get("_files", [])
        if not urls and not uploads:
            return _response(400, "")
        urls += [("upload", data) for data in uploads]
        stopped = _truthy(p.get("stopped")) or _truthy(p.get("paused"))
        # Automatic Torrent Management: when on (the request's autoTMM, else the server default),
        # savepath is ignored and the category's or the default save path is used.
        tmm = _truthy(p["autoTMM"]) if "autoTMM" in p else self.preferences.get("auto_tmm_enabled", False)
        added, pending, failed, ids = 0, 0, 0, []
        for url in urls:
            size, has_meta = 0, False
            if isinstance(url, tuple):  # an uploaded .torrent file
                try:
                    meta = torrentfile.parse(url[1])
                except torrentfile.TorrentFileError:
                    return _response(415, "")
                h, name, size, has_meta = meta.info_hash, meta.name, meta.size or 0, True
                url = f"magnet:?xt=urn:btih:{h}"  # how the row's magnet_uri looks for a file add
                if self.torrent(h):
                    failed += 1
                    continue
            elif url.startswith("magnet:"):
                h = magnet_hash(url)
                name = next((part[3:] for part in url.split("&") if part.startswith("dn=")), h)
            else:  # qBittorrent fetches the .torrent itself, after answering
                data = self.web.get(url)
                pending += 1  # 5.2.3 reports URL adds as pending: it fetches the file afterwards
                if data is None:
                    continue  # the background download fails and nothing appears
                meta = torrentfile.parse(data)
                h, name, size, has_meta = meta.info_hash, meta.name, meta.size or 0, True
            if self.torrent(h):
                if url.startswith("magnet:"):
                    failed += 1
                continue
            cat = p.get("category", "")
            if cat and cat not in self.categories:
                self.categories[cat] = category(cat, "")
            for tag in [x for x in p.get("tags", "").split(",") if x]:
                if tag not in self.tags:
                    self.tags.append(tag)
            t = make_torrent(name, "stoppedDL" if stopped else "metaDL", n=0, size=0, progress=0.0,
                             category=cat, tags=", ".join(sorted(x for x in p.get("tags", "").split(",") if x)))
            if "useDownloadPath" in p:
                use_dl = _truthy(p["useDownloadPath"])
            else:
                use_dl = self.preferences["temp_path_enabled"]
            dl_path = (p.get("downloadPath") or self.preferences["temp_path"]) if use_dl else ""
            t.update(hash=h, infohash_v1=h, download_path=dl_path, magnet_uri=url if url.startswith("magnet:") else f"magnet:?xt=urn:btih:{h}",
                     has_metadata=has_meta, size=size, total_size=size, amount_left=size,
                     pieces_num=-(-size // t["piece_size"]) if size else 0, pieces_have=0,
                     save_path=("/data/torrents/completed" if tmm else p.get("savepath"))
                     or "/data/torrents/completed", auto_tmm=tmm,
                     added_on=1_790_100_000 + len(self.torrents), completion_on=-1, priority=len(self.torrents))
            t["name"] = p.get("rename") or name
            t["content_path"] = f"{t['download_path'] or t['save_path']}/{name}"
            if self.add_settles_through:  # e.g. checkingResumeData before the requested state
                t["_settle"] = t["state"]
                t["state"] = self.add_settles_through
            self.torrents.append(t)
            if url.startswith("magnet:"):  # magnets and uploads are added at once; URLs are pending
                added += 1
                ids.append(h)
        if self.legacy_add_answer:
            return _response(200, "Ok." if added or pending else "Fails.")
        return _response(200, {"added_torrent_ids": ids, "failure_count": failed,
                               "pending_count": pending, "success_count": added})

    def fetch_metadata(self, torrent_hash: str, size: int = 3_200_000_000) -> None:
        """Simulate the swarm delivering the metadata of an added magnet."""
        t = self.torrent(torrent_hash)
        t.update(has_metadata=True, size=size, total_size=size, amount_left=size,
                 pieces_num=-(-size // t["piece_size"]))
        if t["state"] == "metaDL":
            t["state"] = "downloading"

    @staticmethod
    def _stop(t: dict[str, Any], p: dict[str, Any]) -> None:
        t["state"] = "stoppedUP" if t["progress"] >= 1 else "stoppedDL"
        t["dlspeed"] = t["upspeed"] = 0

    @staticmethod
    def _start(t: dict[str, Any], p: dict[str, Any]) -> None:
        if t["state"] in ("stoppedDL", "stoppedUP"):
            if t["progress"] >= 1:
                t["state"] = "stalledUP"
            else:
                t["state"] = "downloading" if t["has_metadata"] else "metaDL"

    def _recheck(self, t: dict[str, Any], p: dict[str, Any]) -> None:
        """Observed on 5.2.3: checkingDL for a while, then back to the previous state."""
        self.rechecked.append(t["hash"])
        after = t["state"]
        if self.recheck_resumes and after.startswith("stopped"):  # older qBittorrent behavior
            self._start(t, p)
            after = t["state"]
        t["_settle"] = after
        t["state"] = "checkingUP" if t["progress"] >= 1 else "checkingDL"

    def _set_category(self, p: dict[str, Any]) -> requests.Response:
        cat = p.get("category", "")
        if cat and cat not in self.categories:
            return _response(409, "Incorrect category name")
        return self._for_hashes(lambda t, q: t.__setitem__("category", cat))(p)

    def _create_category(self, p: dict[str, Any]) -> requests.Response:
        name = p.get("category", "")
        if not name:
            return _response(400, "")
        if name in self.categories:
            return _response(409, "Unable to create category")
        self.categories[name] = category(name, p.get("savePath", ""))
        return _response(200, "")

    def _remove_categories(self, p: dict[str, Any]) -> requests.Response:
        for name in p.get("categories", "").split("\n"):
            self.categories.pop(name, None)
            for t in self.torrents:
                if t["category"] == name:
                    t["category"] = ""
        return _response(200, "")

    def _add_tags(self, t: dict[str, Any], p: dict[str, Any]) -> None:
        have = [x.strip() for x in t["tags"].split(",") if x.strip()]
        for tag in [x.strip() for x in p.get("tags", "").split(",") if x.strip()]:
            if tag not in self.tags:
                self.tags.append(tag)
            if tag not in have:
                have.append(tag)
        t["tags"] = ", ".join(sorted(have))

    @staticmethod
    def _remove_tags(t: dict[str, Any], p: dict[str, Any]) -> None:
        drop = {x.strip() for x in p.get("tags", "").split(",") if x.strip()}
        t["tags"] = ", ".join(x.strip() for x in t["tags"].split(",") if x.strip() and x.strip() not in drop)

    def _delete_tags(self, p: dict[str, Any]) -> requests.Response:
        drop = {x.strip() for x in p.get("tags", "").split(",") if x.strip()}
        self.tags = [t for t in self.tags if t not in drop]
        for t in self.torrents:
            self._remove_tags(t, {"tags": ",".join(drop)})
        return _response(200, "")

    def _rename(self, p: dict[str, Any]) -> requests.Response:
        t = self.torrent(p.get("hash", "").lower())
        if t is None:
            return _response(404, "")
        if not p.get("name", "").strip():
            return _response(409, "Incorrect torrent name")
        t["name"] = p["name"]
        return _response(200, "")

    def _set_location(self, p: dict[str, Any]) -> requests.Response:
        location = p.get("location", "")
        if not location:
            return _response(400, "Save path cannot be empty")
        return self._for_hashes(lambda t, q: t.update(save_path=location))(p)

    def _delete(self, p: dict[str, Any]) -> requests.Response:
        wanted = p.get("hashes", "")
        if not wanted:
            return _response(400, "")
        doomed = {t["hash"] for t in self.torrents} if wanted == "all" else set(wanted.lower().split("|"))
        self.deleted_files.extend(t["hash"] for t in self.torrents
                                  if t["hash"] in doomed and _truthy(p.get("deleteFiles")))
        self.torrents = [t for t in self.torrents if t["hash"] not in doomed]
        return _response(200, "")


def _changed(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """The keys of `new` whose values differ from `old` (how sync deltas report rows)."""
    return {k: v for k, v in new.items() if old.get(k) != v}
