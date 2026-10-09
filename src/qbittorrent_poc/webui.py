"""One method per use case. All qBittorrent wire-format knowledge lives here.

See docs/use-cases.md for what each method was verified against.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .client import QbtClient
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
