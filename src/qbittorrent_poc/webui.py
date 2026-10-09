"""One method per use case. All qBittorrent wire-format knowledge lives here.

See docs/use-cases.md for what each method was verified against.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterable
from typing import Any

from .client import QbtClient
from .errors import QbtError
from .fields import TORRENT_FIELDS, TORRENT_STATES, WEBUI_SECURITY_PREFS  # noqa: F401  (re-exported)

# torrents/info `filter` values in qBittorrent 5.x (the wiki's `paused` is now `stopped`).
FILTERS = (
    "all", "downloading", "seeding", "completed", "stopped", "active", "inactive",
    "running", "stalled", "stalled_uploading", "stalled_downloading", "errored",
)


def join_hashes(hashes: str | Iterable[str] | None) -> str | None:
    """`hashes` params are '|'-separated (or the literal 'all')."""
    if hashes is None or isinstance(hashes, str):
        return hashes
    return "|".join(hashes)


def split_tags(tags: str) -> list[str]:
    """torrents/info returns tags as one comma-separated string ('a, b' or 'a,b')."""
    return [t.strip() for t in tags.split(",") if t.strip()]


class WebUI:
    def __init__(self, client: QbtClient):
        self.client = client

    # -- UC-01: versions -------------------------------------------------------
    def app_version(self) -> str:
        return self.client.get("app/version")

    def webapi_version(self) -> str:
        return self.client.get("app/webapiVersion")

    def build_info(self) -> dict[str, Any]:
        return self.client.get("app/buildInfo")

    def default_save_path(self) -> str:
        return self.client.get("app/defaultSavePath")

    def webui_security_settings(self) -> dict[str, Any]:
        """The WebUI's request checks and ban settings (a safe subset of app/preferences)."""
        prefs = self.client.get("app/preferences")
        return {k: prefs[k] for k in WEBUI_SECURITY_PREFS if k in prefs}

    # -- UC-02: global transfer state -------------------------------------------
    def transfer_info(self) -> dict[str, Any]:
        return self.client.get("transfer/info")

    def alt_speed_limits_enabled(self) -> bool:
        return str(self.client.get("transfer/speedLimitsMode")).strip() == "1"

    # -- UC-03: list torrents ---------------------------------------------------
    def list_torrents(
        self,
        filter: str = "all",
        *,
        category: str | None = None,
        tag: str | None = None,
        sort: str | None = None,
        reverse: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        hashes: str | Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """torrents/info. category/tag: None = any, "" = uncategorized/untagged."""
        if filter not in FILTERS:
            raise ValueError(f"Unknown filter {filter!r}; use one of: {', '.join(FILTERS)}")
        return self.client.get(
            "torrents/info",
            filter=filter,
            category=category,
            tag=tag,
            sort=sort,
            reverse=reverse or None,
            limit=limit,
            offset=offset,
            hashes=join_hashes(hashes),
        )

    # -- UC-04: categories and tags ------------------------------------------------
    def categories(self) -> dict[str, dict[str, Any]]:
        """{name: {name, savePath, download_path, ratio_limit, seeding_time_limit,
        inactive_seeding_time_limit, share_limit_action}}. savePath "" = the default save path."""
        return self.client.get("torrents/categories")

    def tags(self) -> list[str]:
        return self.client.get("torrents/tags")

    # -- UC-05: find a torrent ----------------------------------------------------
    def find_torrents(self, query: str) -> list[dict[str, Any]]:
        """Torrents whose hash starts with `query` (case-insensitive) or whose name contains it.

        An exact hash match wins outright. Matching is done here: the API has no search.
        """
        q = query.strip().lower()
        if not q:
            raise ValueError("Give a hash, a hash prefix, or part of a torrent name.")
        torrents = self.list_torrents()
        exact = [t for t in torrents if t["hash"].lower() == q]
        if exact:
            return exact
        return [t for t in torrents if t["hash"].lower().startswith(q) or q in t["name"].lower()]

    def resolve_hash(self, query: str) -> str:
        """The single torrent matching `query` (see find_torrents), else ValueError listing matches."""
        found = self.find_torrents(query)
        if len(found) == 1:
            return found[0]["hash"]
        if not found:
            raise ValueError(f"No torrent matches {query!r}.")
        names = "; ".join(f"{t['hash'][:8]} {t['name']}" for t in found[:5])
        raise ValueError(f"{len(found)} torrents match {query!r}: {names}. Be more specific.")

    # -- UC-06: torrent details ---------------------------------------------------
    def properties(self, torrent_hash: str) -> dict[str, Any]:
        """torrents/properties. Unknown hash: QbtError 404."""
        return self.client.get("torrents/properties", hash=torrent_hash)

    def files(self, torrent_hash: str, indexes: Iterable[int] | None = None) -> list[dict[str, Any]]:
        """torrents/files: [{index, name, size, progress, priority, is_seed, piece_range, availability}]."""
        idx = "|".join(str(i) for i in indexes) if indexes is not None else None
        return self.client.get("torrents/files", hash=torrent_hash, indexes=idx)

    def trackers(self, torrent_hash: str) -> list[dict[str, Any]]:
        """torrents/trackers, including the DHT/PeX/LSD pseudo-rows (tier < 0)."""
        return self.client.get("torrents/trackers", hash=torrent_hash)

    def webseeds(self, torrent_hash: str) -> list[dict[str, Any]]:
        return self.client.get("torrents/webseeds", hash=torrent_hash)

    # -- UC-07: peers ---------------------------------------------------------------
    def peers(self, torrent_hash: str, rid: int = 0) -> dict[str, Any]:
        """sync/torrentPeers: {rid, full_update, peers: {"ip:port": {...}}, peers_removed?}.

        Pass the returned rid back to get only what changed since.
        """
        return self.client.get("sync/torrentPeers", hash=torrent_hash, rid=rid)

    # -- UC-08: incremental sync ------------------------------------------------------
    def maindata(self, rid: int = 0) -> dict[str, Any]:
        """sync/maindata. rid=0: everything (full_update=true). Pass the returned rid back to get
        only changes: partial torrent rows, *_removed lists and changed server_state keys."""
        return self.client.get("sync/maindata", rid=rid)

    # -- UC-09: logs ---------------------------------------------------------------------
    def main_log(
        self,
        *,
        normal: bool = True,
        info: bool = True,
        warning: bool = True,
        critical: bool = True,
        last_known_id: int = -1,
    ) -> list[dict[str, Any]]:
        """log/main: [{id, message, timestamp, type}], oldest first. type: 1 normal, 2 info,
        4 warning, 8 critical. last_known_id returns only newer entries."""
        return self.client.get(
            "log/main", normal=normal, info=info, warning=warning, critical=critical,
            last_known_id=last_known_id,
        )

    # =====================================================================================
    # Stage 3: changes. These are the raw calls; examples and the MCP server go through
    # qbittorrent_poc.sandbox.Sandbox, which applies TorrentPolicy first.
    # =====================================================================================

    # -- UC-10: add ---------------------------------------------------------------------------
    def add(
        self,
        urls: Iterable[str],
        *,
        savepath: str | None = None,
        category: str | None = None,
        tags: Iterable[str] = (),
        stopped: bool = True,
        rename: str | None = None,
        sequential: bool | None = None,
        skip_checking: bool | None = None,
    ) -> Any:
        """torrents/add from magnet or http(s) URLs. Adds stopped by default.

        5.x renamed the `paused` parameter to `stopped`; both are sent so either server
        generation honors it (errata records which one 5.2.3 reads). Returns the server's
        answer ("Ok." or a JSON summary); raises QbtError 409 when nothing was added.
        """
        urls = list(urls)
        if not urls:
            raise ValueError("Give at least one magnet or http(s) URL.")
        answer = self.client.post(
            "torrents/add",
            {
                "urls": "\n".join(urls),
                "savepath": savepath,
                "category": category,
                "tags": ",".join(tags) or None,
                "stopped": stopped,
                "paused": stopped,
                "rename": rename,
                "sequentialDownload": sequential,
                "skip_checking": skip_checking,
            },
            # torrents/add is documented as multipart/form-data.
            files={"_": (None, "")},
        )
        if isinstance(answer, str) and answer.strip() == "Fails.":
            raise QbtError("torrents/add", 409, "Fails. (already in qBittorrent, or an invalid URL)")
        if isinstance(answer, dict) and answer.get("success_count") == 0 and answer.get("failure_count"):
            raise QbtError("torrents/add", 409, f"nothing added: {answer}")
        return answer

    # -- UC-11: stop, start, recheck, reannounce ------------------------------------------------
    def stop(self, hashes: str | Iterable[str]) -> None:
        self.client.post("torrents/stop", {"hashes": join_hashes(hashes)})

    def start(self, hashes: str | Iterable[str]) -> None:
        self.client.post("torrents/start", {"hashes": join_hashes(hashes)})

    def recheck(self, hashes: str | Iterable[str]) -> None:
        self.client.post("torrents/recheck", {"hashes": join_hashes(hashes)})

    def reannounce(self, hashes: str | Iterable[str]) -> None:
        self.client.post("torrents/reannounce", {"hashes": join_hashes(hashes)})

    # -- UC-12: categories ---------------------------------------------------------------------
    def create_category(self, name: str, save_path: str = "") -> None:
        """409 if the name is invalid or already exists."""
        self.client.post("torrents/createCategory", {"category": name, "savePath": save_path})

    def remove_categories(self, names: Iterable[str]) -> None:
        self.client.post("torrents/removeCategories", {"categories": "\n".join(names)})

    def set_category(self, hashes: str | Iterable[str], category: str) -> None:
        """category "" removes it. 409 if the category doesn't exist."""
        self.client.post("torrents/setCategory", {"hashes": join_hashes(hashes), "category": category})

    # -- UC-13: tags -----------------------------------------------------------------------------
    def add_tags(self, hashes: str | Iterable[str], tags: Iterable[str]) -> None:
        """Tags that don't exist yet are created."""
        self.client.post("torrents/addTags", {"hashes": join_hashes(hashes), "tags": ",".join(tags)})

    def remove_tags(self, hashes: str | Iterable[str], tags: Iterable[str]) -> None:
        tags = list(tags)
        if not tags:
            raise ValueError("Name the tags to remove (an empty list would remove all of them).")
        self.client.post("torrents/removeTags", {"hashes": join_hashes(hashes), "tags": ",".join(tags)})

    def delete_tags(self, tags: Iterable[str]) -> None:
        """Delete tags from qBittorrent entirely (from every torrent)."""
        self.client.post("torrents/deleteTags", {"tags": ",".join(tags)})

    # -- UC-14: rename and move ---------------------------------------------------------------------
    def rename(self, torrent_hash: str, name: str) -> None:
        """The display name only; files on disk keep their names. 409 if name is empty."""
        self.client.post("torrents/rename", {"hash": torrent_hash, "name": name})

    def set_location(self, hashes: str | Iterable[str], location: str) -> None:
        """Move data to a container path. 400 empty, 403 no write access, 409 can't create."""
        self.client.post("torrents/setLocation", {"hashes": join_hashes(hashes), "location": location})

    # -- UC-15: delete ---------------------------------------------------------------------------------
    def delete(self, hashes: str | Iterable[str], *, delete_files: bool) -> None:
        """Remove torrents; delete_files=True also removes the downloaded data. No default on
        purpose. The server answers 200 even for unknown hashes."""
        self.client.post("torrents/delete", {"hashes": join_hashes(hashes), "deleteFiles": delete_files})


_BTIH = re.compile(r"xt=urn:btih:([0-9a-zA-Z]+)")


def magnet_hash(uri: str) -> str:
    """The v1 info hash of a magnet link as 40 lowercase hex characters (also from base32)."""
    m = _BTIH.search(uri)
    if not m:
        raise ValueError("Not a magnet link with an xt=urn:btih: info hash.")
    value = m.group(1)
    if len(value) == 40 and all(c in "0123456789abcdefABCDEF" for c in value):
        return value.lower()
    if len(value) == 32:
        return base64.b32decode(value.upper()).hex()
    raise ValueError(f"Unrecognized info hash {value!r} in the magnet link.")
