"""What the PoC (and later the MCP server) may change on the real qBittorrent.

The NAS runs real torrents, so every change is confined to a sandbox:
- Torrents: only ones carrying the sandbox tag (default `poc`). New torrents always get it,
  and the tag can't be removed through the sandbox, so nothing can leave it.
- Paths: save paths and moves stay inside the sandbox save path (a container path).
- Capabilities: writes and deletes are separate opt-ins.

Checks run locally before any request; a PolicyError means nothing was sent.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .webui import split_tags


class PolicyError(PermissionError):
    """An operation was refused by the local policy (not by qBittorrent)."""


def normalize(path: str) -> str:
    if not path or not path.startswith("/"):
        raise PolicyError(f"Paths must be absolute container paths (e.g. /data/torrents/...): {path!r}")
    return posixpath.normpath(path)


@dataclass(frozen=True)
class TorrentPolicy:
    sandbox_tag: str = "poc"
    sandbox_path: str | None = None
    allow_writes: bool = False
    allow_delete: bool = False

    def __post_init__(self) -> None:
        if not self.sandbox_tag or "," in self.sandbox_tag:
            raise ValueError("The sandbox tag must be a single, non-empty tag.")
        if self.sandbox_path:
            object.__setattr__(self, "sandbox_path", normalize(self.sandbox_path).rstrip("/") or "/")

    # -- capabilities ------------------------------------------------------------------
    def require_writes(self) -> None:
        if not self.allow_writes:
            raise PolicyError("Changes are disabled (set QBT_MCP_ALLOW_WRITES=true).")

    def require_delete(self) -> None:
        if not self.allow_delete:
            raise PolicyError("Deleting torrents is disabled (set QBT_MCP_ALLOW_DELETE=true).")

    # -- torrents ------------------------------------------------------------------------
    def check_torrents(self, hashes: Iterable[str], rows: list[dict[str, Any]]) -> list[str]:
        """Given the hashes asked for and their torrents/info rows, return the hashes if every
        one exists and carries the sandbox tag; else PolicyError naming the offenders."""
        wanted = [h.lower() for h in hashes]
        if not wanted:
            raise PolicyError("Name at least one torrent.")
        if any(h == "all" for h in wanted):
            raise PolicyError("'all' is not allowed: name the sandbox torrents explicitly.")
        found = {t["hash"].lower(): t for t in rows}
        missing = [h for h in wanted if h not in found]
        if missing:
            raise PolicyError(f"Unknown torrent(s): {', '.join(h[:8] for h in missing)}.")
        outside = [found[h] for h in wanted if self.sandbox_tag not in split_tags(found[h]["tags"])]
        if outside:
            names = "; ".join(f"{t['hash'][:8]} {t['name']}" for t in outside[:5])
            raise PolicyError(
                f"Only torrents tagged {self.sandbox_tag!r} may be changed. Not tagged: {names}."
            )
        return wanted

    def check_tags_removal(self, tags: Iterable[str]) -> list[str]:
        tags = [t.strip() for t in tags if t.strip()]
        if self.sandbox_tag in tags:
            raise PolicyError(f"The sandbox tag {self.sandbox_tag!r} can't be removed: it keeps the torrent in the sandbox.")
        return tags

    # -- paths ----------------------------------------------------------------------------
    def check_path(self, path: str) -> str:
        """The normalized path if it is the sandbox path or inside it."""
        if not self.sandbox_path:
            raise PolicyError("No sandbox save path configured (set QBT_SANDBOX_SAVEPATH).")
        norm = normalize(path)
        if norm == self.sandbox_path or norm.startswith(self.sandbox_path + "/"):
            return norm
        raise PolicyError(f"{path!r} is outside the sandbox save path {self.sandbox_path}.")
