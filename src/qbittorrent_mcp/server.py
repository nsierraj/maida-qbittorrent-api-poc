"""MCP server exposing qBittorrent use cases (see docs/mcp-server.md).

Safety model:
- Read tools are always available.
- Change tools exist only when QBT_MCP_ALLOW_WRITES=true; the delete tool only when
  QBT_MCP_ALLOW_DELETE=true as well.
- Every change goes through qbittorrent_poc.Sandbox: only torrents tagged QBT_SANDBOX_TAG, data
  only inside QBT_SANDBOX_SAVEPATH, the sandbox tag can't be removed, `all` is refused. Refusals
  happen before any request reaches qBittorrent.
- Never exposed: app/setPreferences, app/shutdown, the full app/preferences (it holds secrets).

The API key comes from the same .env as the PoC and never appears in tool output. Nothing may
print to stdout: with the stdio transport, stdout is the protocol channel.
"""

from __future__ import annotations

import functools
import os
import threading
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from qbittorrent_poc import (FILTERS, TORRENT_FIELDS, PolicyError, QbtClient, QbtError, Sandbox, Settings,
                             TorrentPolicy, WebUI, fields, fmt, samples, torrentfile)
from qbittorrent_poc.torrentfile import TorrentFileError
from qbittorrent_poc.webui import split_tags

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
ADD = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)  # downloads
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

MAX_TORRENTS_PER_CALL = 50
LOG_LEVELS = {"normal": 1, "info": 2, "warning": 4, "critical": 8}


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class ServerConfig:
    settings: Settings | None
    policy: TorrentPolicy

    @classmethod
    def from_env(cls) -> ServerConfig:
        settings = Settings.from_env()  # also loads .env
        return cls(
            settings=settings,
            policy=TorrentPolicy(
                settings.sandbox_tag,
                settings.sandbox_savepath,
                allow_writes=_flag("QBT_MCP_ALLOW_WRITES"),
                allow_delete=_flag("QBT_MCP_ALLOW_DELETE"),
            ),
        )


@dataclass
class QbtSession:
    """One shared client, created on the first tool call. Calls are serialized: tools run in
    worker threads and a requests.Session isn't safe for concurrent use."""

    client_factory: Callable[[], QbtClient]
    lock: threading.Lock = field(default_factory=threading.Lock)
    _api: WebUI | None = None

    def api(self) -> WebUI:
        if self._api is None:
            self._api = WebUI(self.client_factory())
        return self._api

    def close(self) -> None:
        if self._api is not None:
            self._api.client.close()
            self._api = None


def client_factory(settings: Settings) -> Callable[[], QbtClient]:
    def make() -> QbtClient:
        client = settings.client()
        try:
            client.get("app/webapiVersion")  # the auth probe: API keys can't call auth/login
        except requests.exceptions.ConnectionError as e:
            client.close()
            raise ToolError(f"Cannot reach qBittorrent at {client.base_url} ({e}). Check QBT_HOST and QBT_PORT.")
        except QbtError as e:
            client.close()
            if e.is_auth_error:
                raise ToolError("qBittorrent rejected the API key. Check QBT_API_KEY "
                                "(WebUI → Options → Web UI → API Key).")
            raise ToolError(f"Unexpected answer from qBittorrent: {e}")
        return client

    return make


# -- result shaping: compact, human-readable, JSON-friendly ----------------------------------
def _iso(epoch: int | None) -> str | None:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat() if epoch and epoch > 0 else None


def _torrent(t: dict[str, Any], sandbox_tag: str) -> dict[str, Any]:
    tags = split_tags(t.get("tags", ""))
    return {
        "hash": t["hash"],
        "name": t["name"],
        "state": t["state"],
        "progress_percent": round(t["progress"] * 100, 1),
        "size": fmt.size(t["size"]),
        "completed": fmt.size(t["completed"]),
        "download_speed": fmt.speed(t["dlspeed"]),
        "upload_speed": fmt.speed(t["upspeed"]),
        "eta": fmt.duration(t["eta"]),
        "ratio": round(t["ratio"], 3),
        "category": t["category"] or None,
        "tags": tags,
        "added": _iso(t["added_on"]),
        "completed_on": _iso(t["completion_on"]),
        "save_path": t["save_path"],
        "in_sandbox": sandbox_tag in tags,
    }


def _peer_summary(peers: dict[str, Any]) -> dict[str, Any]:
    rows = list(peers.values())

    def top(key: str) -> dict[str, int]:
        return dict(Counter(p.get(key) or "unknown" for p in rows).most_common(5))

    return {"connected": len(rows), "clients": top("client"), "countries": top("country_code"),
            "connection_types": top("connection")}


def build_server(config: ServerConfig, session: QbtSession | None = None) -> MCPServer:
    if session is None:
        if config.settings is None:
            raise ValueError("settings are required when no session is given")
        session = QbtSession(client_factory(config.settings))
    policy = config.policy
    tag = policy.sandbox_tag

    @asynccontextmanager
    async def lifespan(app: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            session.close()

    changes = "disabled"
    if policy.allow_writes:
        changes = (f"enabled, but only for torrents tagged {tag!r}, with data inside {policy.sandbox_path}"
                   f"; deleting is {'enabled' if policy.allow_delete else 'disabled'}")
    server = MCPServer(
        name="qbittorrent",
        instructions=(
            "Tools for a qBittorrent 5.x server on a NAS, through its WebUI API. Identify torrents by "
            "info hash, a hash prefix, or part of the name; ambiguous matches are refused with the "
            "candidates listed. Paths are paths inside the qBittorrent container (/data/torrents/...). "
            f"Changes are {changes}. Torrents outside the sandbox can be read but never changed."
        ),
        lifespan=lifespan,
    )

    def tool(annotations: ToolAnnotations) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a tool: serialize qBittorrent access and turn known failures into ToolErrors."""

        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with session.lock:
                    try:
                        return fn(*args, **kwargs)
                    except PolicyError as e:
                        raise ToolError(f"Refused by the sandbox policy (nothing was sent): {e}") from e
                    except QbtError as e:
                        raise ToolError(f"qBittorrent: {e}") from e
                    except (ValueError, TimeoutError) as e:  # bad identifiers, filters, slow changes
                        raise ToolError(str(e)) from e
                    except requests.RequestException as e:
                        raise ToolError(f"Request to qBittorrent failed: {e}") from e

            server.add_tool(wrapper, annotations=annotations)
            return fn

        return register

    def api() -> WebUI:
        return session.api()

    def box() -> Sandbox:
        return Sandbox(api(), policy)

    def resolve(torrents: list[str]) -> list[tuple[str, str]]:
        """[(hash, name)] for each identifier; ValueError (→ ToolError) on no or several matches."""
        if not torrents:
            raise ValueError("Name at least one torrent.")
        if len(torrents) > MAX_TORRENTS_PER_CALL:
            raise ValueError(f"At most {MAX_TORRENTS_PER_CALL} torrents per call.")
        out = []
        for ident in torrents:
            h = api().resolve_hash(ident)
            out.append((h, api().list_torrents(hashes=[h])[0]["name"]))
        return out

    def states(hashes: list[str]) -> list[dict[str, Any]]:
        return [_torrent(t, tag) for t in api().list_torrents(hashes=hashes)]

    # == read-only tools ===========================================================================
    @tool(READ_ONLY)
    def qbt_server_info() -> dict[str, Any]:
        """qBittorrent version, connection and VPN status (external IP), speeds and limits, free disk
        space, torrent counts by state, and what this MCP server is allowed to change."""
        a = api()
        data = a.maindata()
        state = data.get("server_state", {})
        by_state = Counter(t.get("state") for t in data.get("torrents", {}).values())
        return {
            "qbittorrent_version": a.app_version(),
            "webapi_version": a.webapi_version(),
            "connection_status": state.get("connection_status"),
            "external_ip_v4": state.get("last_external_address_v4") or None,
            "external_ip_v6": state.get("last_external_address_v6") or None,
            "dht_nodes": state.get("dht_nodes"),
            "download_speed": fmt.speed(state.get("dl_info_speed", 0)),
            "upload_speed": fmt.speed(state.get("up_info_speed", 0)),
            "download_limit": fmt.limit(state.get("dl_rate_limit", 0)),
            "upload_limit": fmt.limit(state.get("up_rate_limit", 0)),
            "alternative_speed_limits": state.get("use_alt_speed_limits"),
            "free_disk_space": fmt.size(state.get("free_space_on_disk", -1)),
            "all_time_downloaded": fmt.size(state.get("alltime_dl", -1)),
            "all_time_uploaded": fmt.size(state.get("alltime_ul", -1)),
            "default_save_path": a.default_save_path(),
            "torrents_total": sum(by_state.values()),
            "torrents_by_state": dict(by_state.most_common()),
            "server_policy": {
                "changes_enabled": policy.allow_writes,
                "delete_enabled": policy.allow_delete,
                "sandbox_tag": tag,
                "sandbox_path": policy.sandbox_path,
            },
        }

    @tool(READ_ONLY)
    def qbt_list_torrents(
        filter: str = "all",
        category: str | None = None,
        tag_name: str | None = None,
        name_contains: str | None = None,
        sort: str = "added_on",
        reverse: bool = True,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List torrents, newest first by default.
        filter: all|downloading|seeding|completed|stopped|active|inactive|running|stalled|
        stalled_uploading|stalled_downloading|errored. category / tag_name: exact match ("" means
        none). name_contains: case-insensitive. sort: any torrent field (added_on, name, size,
        progress, dlspeed, upspeed, ratio, eta, ...). limit 1-200; use next_offset to page."""
        if filter not in FILTERS:
            raise ValueError(f"filter must be one of: {', '.join(FILTERS)}")
        if sort not in TORRENT_FIELDS:
            raise ValueError("sort must be a torrent field such as added_on, name, size, progress, dlspeed, ratio.")
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("limit must be 1-200 and offset >= 0.")
        rows = api().list_torrents(filter, category=category, tag=tag_name, sort=sort, reverse=reverse)
        if name_contains:
            needle = name_contains.lower()
            rows = [t for t in rows if needle in t["name"].lower()]
        page = rows[offset:offset + limit]
        more = offset + len(page) < len(rows)
        return {"total": len(rows), "count": len(page), "offset": offset, "has_more": more,
                "next_offset": offset + len(page) if more else None,
                "torrents": [_torrent(t, tag) for t in page]}

    @tool(READ_ONLY)
    def qbt_torrent_details(torrent: str, max_files: int = 20) -> dict[str, Any]:
        """Everything about one torrent (hash, hash prefix or part of the name): status, transfer
        totals, swarm, files (largest first, up to max_files), trackers (host only) and a summary
        of connected peers (no IP addresses)."""
        a = api()
        (h, _), = resolve([torrent])
        row = a.list_torrents(hashes=[h])[0]
        props = a.properties(h)
        files = sorted(a.files(h), key=lambda f: f["size"], reverse=True)
        trackers = a.trackers(h)
        peers = a.peers(h).get("peers", {})
        return {
            **_torrent(row, tag),
            "verified_pieces": f"{props.get('pieces_have')}/{props.get('pieces_num')}",
            "piece_size": fmt.size(props.get("piece_size", -1)),
            "total_downloaded": fmt.size(props.get("total_downloaded", -1)),
            "total_uploaded": fmt.size(props.get("total_uploaded", -1)),
            "wasted": fmt.size(props.get("total_wasted", -1)),
            "seeds": f"{props.get('seeds')} connected / {props.get('seeds_total')} in swarm",
            "peers": f"{props.get('peers')} connected / {props.get('peers_total')} in swarm",
            "average_download_speed": fmt.speed(props.get("dl_speed_avg", 0)),
            "time_active": fmt.duration(props.get("time_elapsed", -1)),
            "seeding_time": fmt.duration(props.get("seeding_time", -1)),
            "private": props.get("private", props.get("is_private")),
            "comment": props.get("comment") or None,
            "files_total": len(files),
            "files": [{"name": f["name"], "size": fmt.size(f["size"]),
                       "progress_percent": round(f["progress"] * 100, 1),
                       "priority": fields.FILE_PRIORITIES.get(f["priority"], f["priority"])}
                      for f in files[:max_files]],
            "trackers": [{"tracker": samples.tracker_host(t["url"]),
                          "status": fields.TRACKER_STATUSES.get(t["status"], t["status"]),
                          "seeds": t["num_seeds"], "leeches": t["num_leeches"],
                          "message": samples.mask_ips(t.get("msg", "")) or None} for t in trackers],
            "connected_peers": _peer_summary(peers),
        }

    @tool(READ_ONLY)
    def qbt_list_categories_and_tags() -> dict[str, Any]:
        """Categories (with save path and torrent count) and tags (with torrent count)."""
        a = api()
        torrents = a.list_torrents()
        per_cat = Counter(t["category"] for t in torrents)
        per_tag = Counter(x for t in torrents for x in split_tags(t["tags"]))
        return {
            "categories": [{"name": n, "save_path": c.get("savePath") or "(default save path)",
                            "torrents": per_cat.get(n, 0)} for n, c in sorted(a.categories().items())],
            "uncategorized_torrents": per_cat.get("", 0),
            "tags": [{"name": x, "torrents": per_tag.get(x, 0)} for x in sorted(a.tags())],
            "sandbox_tag": tag,
        }

    @tool(READ_ONLY)
    def qbt_whats_changed(since: int = 0) -> dict[str, Any]:
        """What changed since an earlier call. First call with since=0 (a snapshot); then pass the
        returned `since` to get only torrents added, removed or changed, and changed server totals."""
        a = api()
        data = a.maindata(since)
        names = {t["hash"]: t["name"] for t in a.list_torrents()}
        if data.get("full_update"):
            by_state = Counter(t.get("state") for t in data.get("torrents", {}).values())
            return {"since": data["rid"], "full_snapshot": True, "torrents_total": sum(by_state.values()),
                    "torrents_by_state": dict(by_state.most_common()),
                    "next": "Call again with this `since` value to see only what changes."}
        added, changed = [], []
        for h, delta in data.get("torrents", {}).items():
            entry = {"hash": h, "name": names.get(h, delta.get("name", h))}
            if "added_on" in delta and "name" in delta:
                added.append({**entry, "state": delta.get("state")})
            else:
                changed.append({**entry, "changes": delta})
        return {
            "since": data["rid"],
            "full_snapshot": False,
            "added": added,
            "changed": changed,
            "removed": data.get("torrents_removed", []),
            "server_changes": data.get("server_state", {}),
            "categories_changed": sorted(data.get("categories", {})),
            "categories_removed": data.get("categories_removed", []),
            "tags_added": data.get("tags", []),
            "tags_removed": data.get("tags_removed", []),
        }

    @tool(READ_ONLY)
    def qbt_main_log(min_level: str = "warning", limit: int = 20, after_id: int = -1) -> dict[str, Any]:
        """Recent qBittorrent log entries at or above min_level (normal|info|warning|critical),
        newest last. Pass the returned last_id as after_id to get only newer entries. IP addresses
        in messages are masked."""
        if min_level not in LOG_LEVELS:
            raise ValueError(f"min_level must be one of: {', '.join(LOG_LEVELS)}")
        floor = LOG_LEVELS[min_level]
        flags = {name: bit >= floor for name, bit in LOG_LEVELS.items()}
        entries = api().main_log(last_known_id=after_id, **flags)
        newest = entries[-max(1, min(limit, 200)):]
        return {
            "last_id": entries[-1]["id"] if entries else after_id,
            "entries": [{"id": e["id"], "time": _iso(e["timestamp"]),
                         "level": fields.LOG_TYPES.get(e["type"], str(e["type"])),
                         "message": samples.mask_ips(e["message"])} for e in newest],
        }

    # == change tools (opt-in, sandbox only) =========================================================
    if policy.allow_writes:

        @tool(ADD)
        def qbt_add_torrent(source: str, category: str | None = None, tags: list[str] | None = None,
                            start: bool = False) -> dict[str, Any]:
            """Add a torrent from a magnet link or an http(s) URL of a .torrent file, into the sandbox
            (tagged and saved inside the sandbox path). Added stopped unless start=true. category
            must already exist. Only add content that is legal to download."""
            a, b = api(), box()
            try:
                h, name, _ = torrentfile.identify(source)
            except TorrentFileError as e:
                raise ValueError(str(e)) from e
            existing = a.list_torrents(hashes=[h])
            if existing:
                where = "in the sandbox" if tag in split_tags(existing[0]["tags"]) else "outside the sandbox"
                raise ValueError(f"{existing[0]['name']} ({h[:8]}) is already in qBittorrent, {where}.")
            if category and category not in a.categories():
                raise ValueError(f"Unknown category {category!r}; existing: {', '.join(sorted(a.categories())) or 'none'}.")
            b.add([source], category=category, tags=tags or [], stopped=not start)
            row = b.wait_settled(h, timeout=90)
            try:
                policy.check_row(row)
            except PolicyError:
                b.api.delete([h], delete_files=True)  # ours, just added, nothing worth keeping
                raise
            return {**_torrent(row, tag), "started": start}

        @tool(WRITE)
        def qbt_stop_torrents(torrents: list[str]) -> list[dict[str, Any]]:
            """Stop (pause) sandbox torrents."""
            hashes = [h for h, _ in resolve(torrents)]
            b = box()
            b.stop(hashes)
            for h in hashes:
                b.wait_for(h, lambda r: r is not None and r["state"].startswith("stopped"), timeout=30)
            return states(hashes)

        @tool(WRITE)
        def qbt_start_torrents(torrents: list[str]) -> list[dict[str, Any]]:
            """Start (resume) sandbox torrents."""
            hashes = [h for h, _ in resolve(torrents)]
            b = box()
            b.start(hashes)
            for h in hashes:
                b.wait_for(h, lambda r: r is not None and not r["state"].startswith("stopped"), timeout=30)
            return states(hashes)

        @tool(WRITE)
        def qbt_recheck_torrents(torrents: list[str]) -> list[dict[str, Any]]:
            """Re-verify the downloaded data of sandbox torrents. Large torrents take a while; the
            state shows checkingDL/checkingUP until done."""
            hashes = [h for h, _ in resolve(torrents)]
            box().recheck(hashes)
            return states(hashes)

        @tool(WRITE)
        def qbt_set_category(torrents: list[str], category: str) -> list[dict[str, Any]]:
            """Set the category of sandbox torrents ("" removes it). The category must exist."""
            hashes = [h for h, _ in resolve(torrents)]
            box().set_category(hashes, category)
            return states(hashes)

        @tool(WRITE)
        def qbt_add_tags(torrents: list[str], tags: list[str]) -> list[dict[str, Any]]:
            """Add tags to sandbox torrents (missing tags are created)."""
            hashes = [h for h, _ in resolve(torrents)]
            box().add_tags(hashes, tags)
            return states(hashes)

        @tool(WRITE)
        def qbt_remove_tags(torrents: list[str], tags: list[str]) -> list[dict[str, Any]]:
            """Remove tags from sandbox torrents. The sandbox tag itself can't be removed."""
            hashes = [h for h, _ in resolve(torrents)]
            box().remove_tags(hashes, tags)
            return states(hashes)

        @tool(WRITE)
        def qbt_rename_torrent(torrent: str, new_name: str) -> dict[str, Any]:
            """Rename a sandbox torrent's display name (files on disk keep their names)."""
            (h, _), = resolve([torrent])
            box().rename(h, new_name)
            return states([h])[0]

        @tool(WRITE)
        def qbt_move_torrents(torrents: list[str], location: str) -> list[dict[str, Any]]:
            """Move sandbox torrents' data to another folder inside the sandbox path (a container path)."""
            hashes = [h for h, _ in resolve(torrents)]
            b = box()
            target = policy.check_path(location)
            b.set_location(hashes, target)
            for h in hashes:
                b.wait_for(h, lambda r: r is not None and r["save_path"].rstrip("/") == target, timeout=120)
            return states(hashes)

    if policy.allow_writes and policy.allow_delete:

        @tool(DESTRUCTIVE)
        def qbt_delete_torrents(torrents: list[str], delete_files: bool) -> dict[str, Any]:
            """Remove sandbox torrents. delete_files=true also deletes their downloaded data from the
            NAS; false keeps the files. There is no undo."""
            pairs = resolve(torrents)
            b = box()
            b.delete([h for h, _ in pairs], delete_files=delete_files)
            for h, _ in pairs:
                b.wait_for(h, lambda r: r is None, timeout=60)
            return {"deleted": [{"hash": h, "name": n} for h, n in pairs], "files_deleted": delete_files}

    # == prompts: ready-made tasks that combine the tools ===========================================
    # Prompts only produce instructions; the model still calls the tools, so they never bypass
    # the policy above.
    @server.prompt(title="Download status")
    def download_status() -> str:
        """A status report: what's downloading or stuck, errors, VPN and disk space."""
        return (
            "Give me a status report of qBittorrent.\n"
            "1. Call qbt_server_info. Report the connection status and external IP (it should be the "
            "VPN's, not my home IP; say so if connection_status is not 'connected'), speeds and "
            "limits, and free disk space.\n"
            "2. Call qbt_list_torrents with filter=downloading, then filter=stalled, then filter=errored. "
            "Show a table: name, state, progress, speed, ETA.\n"
            "3. For anything stalled or errored, call qbt_torrent_details and explain the likely cause "
            "(no seeds, tracker not working, missing files).\n"
            "4. Call qbt_main_log with min_level=warning, limit=10 and summarize anything new.\n"
            "Don't change anything."
        )

    @server.prompt(title="Clean up the sandbox")
    def clean_sandbox() -> str:
        """Find torrents in the sandbox and offer to remove them."""
        steps = [
            f"Find torrents in the sandbox (tag {tag!r}).",
            f"1. Call qbt_list_torrents with tag_name={tag!r} and show them: name, state, size, added.",
            "2. Ask me to confirm before removing anything.",
        ]
        if policy.allow_writes and policy.allow_delete:
            steps.append("3. After I confirm, call qbt_delete_torrents with delete_files=true, then list "
                         "again to show they're gone.")
        else:
            steps.append("3. Deleting is disabled here (QBT_MCP_ALLOW_WRITES and QBT_MCP_ALLOW_DELETE); "
                         "tell me to run `uv run examples/03_lifecycle.py --cleanup` instead.")
        return "\n".join(steps)

    return server


def main() -> None:
    config = ServerConfig.from_env()  # also loads .env
    build_server(config).run("stdio")


if __name__ == "__main__":
    main()
