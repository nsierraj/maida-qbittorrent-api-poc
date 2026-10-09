"""One method per use case. All qBittorrent wire-format knowledge lives here.

See docs/use-cases.md for what each method was verified against.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .client import QbtClient

# torrents/info fields, as sent by the real server (qBittorrent 5.2.3, WebAPI 2.15.1, recorded
# 2026-10-09). The wiki (5.0) lists fewer and says `isPrivate`; 5.2.3 sends `private` instead.
# examples/01_discover.py reports any difference.
TORRENT_FIELDS = (
    "added_on", "amount_left", "auto_tmm", "availability", "category", "comment", "completed",
    "completion_on", "connections_count", "connections_limit", "content_path", "created_by",
    "creation_date", "dl_limit", "dlspeed", "download_path", "downloaded", "downloaded_session",
    "eta", "f_l_piece_prio", "force_start", "has_metadata", "hash", "inactive_seeding_time_limit",
    "infohash_v1", "infohash_v2", "last_activity", "magnet_uri", "max_inactive_seeding_time",
    "max_ratio", "max_seeding_time", "name", "num_complete", "num_incomplete", "num_leechs",
    "num_seeds", "piece_size", "pieces_have", "pieces_num", "popularity", "priority", "private",
    "progress", "ratio", "ratio_limit", "reannounce", "root_path", "save_path", "seeding_time",
    "seeding_time_limit", "seen_complete", "seq_dl", "share_limit_action", "size", "state",
    "super_seeding", "tags", "time_active", "total_size", "total_wasted", "tracker",
    "trackers_count", "up_limit", "uploaded", "uploaded_session", "upspeed",
)

# app/preferences keys that explain how the WebUI treats requests. Never return preferences
# wholesale: they include secrets (proxy and SMTP passwords, the WebUI password hash).
WEBUI_SECURITY_PREFS = (
    "web_ui_port", "web_ui_host_header_validation_enabled", "web_ui_domain_list",
    "web_ui_csrf_protection_enabled", "web_ui_clickjacking_protection_enabled",
    "bypass_local_auth", "bypass_auth_subnet_whitelist_enabled", "web_ui_max_auth_fail_count",
    "web_ui_ban_duration", "web_ui_session_timeout", "use_https", "web_ui_reverse_proxy_enabled",
)

# Torrent `state` values in qBittorrent 5.x (the wiki still says pausedUP/pausedDL).
TORRENT_STATES = (
    "error", "missingFiles", "uploading", "stoppedUP", "queuedUP", "stalledUP", "checkingUP",
    "forcedUP", "allocating", "downloading", "metaDL", "forcedMetaDL", "stoppedDL", "queuedDL",
    "stalledDL", "checkingDL", "forcedDL", "checkingResumeData", "moving", "unknown",
)

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
