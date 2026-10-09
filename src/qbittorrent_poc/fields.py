"""Reference field sets for each endpoint, used to spot what the real server adds or drops.

Each set says where it came from. "real 5.2.3" sets were recorded from the user's server and are
authoritative; "wiki" and "source" sets are unverified until an example run confirms them, and
examples print the difference (see `diff_fields`). Update a set when the errata say so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

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

# torrents/properties (wiki 5.0; unverified).
PROPERTIES_FIELDS = (
    "addition_date", "comment", "completion_date", "created_by", "creation_date", "dl_limit",
    "dl_speed", "dl_speed_avg", "eta", "isPrivate", "last_seen", "nb_connections",
    "nb_connections_limit", "peers", "peers_total", "piece_size", "pieces_have", "pieces_num",
    "reannounce", "save_path", "seeding_time", "seeds", "seeds_total", "share_ratio",
    "time_elapsed", "total_downloaded", "total_downloaded_session", "total_size",
    "total_uploaded", "total_uploaded_session", "total_wasted", "up_limit", "up_speed",
    "up_speed_avg",
)

# torrents/files (wiki 5.0; unverified). priority: 0 skip, 1 normal, 6 high, 7 maximal.
FILE_FIELDS = ("availability", "index", "is_seed", "name", "piece_range", "priority", "progress", "size")
FILE_PRIORITIES = {0: "skip", 1: "normal", 6: "high", 7: "maximal"}

# torrents/trackers (wiki 5.0; unverified). Rows with tier < 0 are DHT, PeX and LSD.
TRACKER_FIELDS = ("msg", "num_downloaded", "num_leeches", "num_peers", "num_seeds", "status", "tier", "url")
TRACKER_STATUSES = {0: "disabled", 1: "not contacted", 2: "working", 3: "updating", 4: "not working"}

# sync/torrentPeers `peers` values (wiki says TODO; from qBittorrent's source; unverified).
PEER_FIELDS = (
    "client", "connection", "country", "country_code", "dl_speed", "downloaded", "files", "flags",
    "flags_desc", "ip", "peer_id_client", "port", "progress", "relevance", "up_speed", "uploaded",
)

# sync/maindata `server_state` (from qBittorrent's source; unverified).
SERVER_STATE_FIELDS = (
    "alltime_dl", "alltime_ul", "average_time_queue", "connection_status", "dht_nodes",
    "dl_info_data", "dl_info_speed", "dl_rate_limit", "free_space_on_disk", "global_ratio",
    "last_external_address_v4", "last_external_address_v6", "queued_io_jobs", "queueing",
    "read_cache_hits", "read_cache_overload", "refresh_interval", "total_buffers_size",
    "total_peer_connections", "total_queued_size", "total_wasted_session", "up_info_data",
    "up_info_speed", "up_rate_limit", "use_alt_speed_limits", "use_subcategories",
    "write_cache_overload",
)

# log/main entries (wiki 5.0; unverified). type is a bit flag.
LOG_FIELDS = ("id", "message", "timestamp", "type")
LOG_TYPES = {1: "normal", 2: "info", 4: "warning", 8: "critical"}


def diff_fields(rows: Iterable[Mapping[str, Any]] | Mapping[str, Any], reference: Iterable[str]) -> tuple[list[str], list[str]]:
    """(fields the server sent that aren't in `reference`, reference fields it didn't send).

    `rows` is one object or a list of objects; an empty list reports no differences.
    """
    rows = [rows] if isinstance(rows, Mapping) else list(rows)
    if not rows:
        return [], []
    seen = set().union(*(r.keys() for r in rows))
    ref = set(reference)
    return sorted(seen - ref), sorted(ref - seen)
