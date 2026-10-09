"""Policy-checked changes: what examples and the MCP server use instead of raw WebUI writes.

Every method checks TorrentPolicy first (no request is sent when it refuses), then calls the
matching WebUI method. Adding always applies the sandbox tag.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

from .errors import QbtError
from .policy import PolicyError, TorrentPolicy
from .webui import WebUI, join_hashes


def _as_list(hashes: str | Iterable[str]) -> list[str]:
    if isinstance(hashes, str):
        return [h for h in hashes.split("|") if h]
    return list(hashes)


class Sandbox:
    def __init__(self, api: WebUI, policy: TorrentPolicy):
        self.api = api
        self.policy = policy

    # -- checks ---------------------------------------------------------------------------
    def _checked(self, hashes: str | Iterable[str]) -> list[str]:
        self.policy.require_writes()
        wanted = _as_list(hashes)
        if not wanted or any(h.lower() == "all" for h in wanted):
            return self.policy.check_torrents(wanted, [])  # raises the right message
        rows = self.api.list_torrents(hashes=wanted)
        return self.policy.check_torrents(wanted, rows)

    def torrents(self) -> list[dict[str, Any]]:
        """Every torrent in the sandbox (read-only, no capability needed)."""
        return self.api.list_torrents(tag=self.policy.sandbox_tag)

    # -- changes -------------------------------------------------------------------------------
    def add(self, urls: Iterable[str], *, savepath: str | None = None, category: str | None = None,
            tags: Iterable[str] = (), stopped: bool = True, **kwargs: Any) -> Any:
        self.policy.require_writes()
        path = self.policy.check_path(savepath or self.policy.sandbox_path or "")
        all_tags = [self.policy.sandbox_tag, *[t for t in tags if t != self.policy.sandbox_tag]]
        return self.api.add(urls, savepath=path, category=category, tags=all_tags, stopped=stopped, **kwargs)

    def stop(self, hashes: str | Iterable[str]) -> None:
        self.api.stop(self._checked(hashes))

    def start(self, hashes: str | Iterable[str]) -> None:
        self.api.start(self._checked(hashes))

    def recheck(self, hashes: str | Iterable[str]) -> None:
        self.api.recheck(self._checked(hashes))

    def reannounce(self, hashes: str | Iterable[str]) -> None:
        self.api.reannounce(self._checked(hashes))

    def set_category(self, hashes: str | Iterable[str], category: str) -> None:
        self.api.set_category(self._checked(hashes), category)

    def ensure_category(self, name: str, save_path: str = "") -> bool:
        """Create the category if it's missing (inside the sandbox path). True if created."""
        self.policy.require_writes()
        if name in self.api.categories():
            return False
        self.api.create_category(name, self.policy.check_path(save_path) if save_path else "")
        return True

    def add_tags(self, hashes: str | Iterable[str], tags: Iterable[str]) -> None:
        self.api.add_tags(self._checked(hashes), tags)

    def remove_tags(self, hashes: str | Iterable[str], tags: Iterable[str]) -> None:
        tags = self.policy.check_tags_removal(tags)
        self.api.remove_tags(self._checked(hashes), tags)

    def rename(self, torrent_hash: str, name: str) -> None:
        (h,) = self._checked([torrent_hash])
        self.api.rename(h, name)

    def set_location(self, hashes: str | Iterable[str], location: str) -> None:
        path = self.policy.check_path(location)
        self.api.set_location(self._checked(hashes), path)

    def delete(self, hashes: str | Iterable[str], *, delete_files: bool) -> None:
        self.policy.require_delete()
        self.api.delete(self._checked(hashes), delete_files=delete_files)

    # -- waiting ---------------------------------------------------------------------------------
    def wait_for(self, torrent_hash: str, predicate: Callable[[dict[str, Any] | None], bool], *,
                 timeout: float = 30, interval: float = 1,
                 on_poll: Callable[[dict[str, Any] | None], None] | None = None) -> dict[str, Any] | None:
        """Poll torrents/info until predicate(row or None) holds. Changes are asynchronous: an
        added magnet appears a moment after torrents/add answers, a stop takes a moment, etc."""
        deadline = time.monotonic() + timeout
        while True:
            rows = self.api.list_torrents(hashes=[torrent_hash])
            row = rows[0] if rows else None
            if on_poll:
                on_poll(row)
            if predicate(row):
                return row
            if time.monotonic() > deadline:
                raise TimeoutError(f"Torrent {torrent_hash[:8]} didn't reach the expected state in {timeout:g}s.")
            time.sleep(interval)

    # -- cleanup -----------------------------------------------------------------------------------
    def cleanup(self, *, delete_files: bool = True, extra_tags: Iterable[str] = (),
                categories: Iterable[str] = ()) -> dict[str, Any]:
        """Delete every sandbox torrent (with its data by default), then the given helper tags and
        any of the given categories no torrent uses any more. Returns what was removed."""
        self.policy.require_delete()
        hashes = [t["hash"] for t in self.torrents()]
        if hashes:
            self.api.delete(join_hashes(hashes), delete_files=delete_files)
            for h in hashes:
                self.wait_for(h, lambda row: row is None, timeout=30)
        tags = [t for t in extra_tags if t != self.policy.sandbox_tag]
        if tags:
            self.api.delete_tags(tags)
        in_use = {t["category"] for t in self.api.list_torrents()}
        removable = [c for c in categories if c in self.api.categories() and c not in in_use]
        if removable:
            self.api.remove_categories(removable)
        return {"torrents": hashes, "tags": tags, "categories": removable}


__all__ = ["PolicyError", "QbtError", "Sandbox", "TorrentPolicy"]
