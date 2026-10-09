"""Redaction for anything the examples print or save from the real server.

Samples go to out/samples/ (gitignored) so the fake server can follow the real one, and example
output gets pasted into chats and issues. Neither may carry torrent names or hashes in samples,
save paths, tracker URLs (private trackers embed passkeys), peer or external IP addresses, or
raw log messages.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REDACTED = "<redacted>"

TORRENT_SECRETS = {"name", "magnet_uri", "tracker", "save_path", "content_path", "download_path",
                   "root_path", "comment", "infohash_v1", "infohash_v2", "hash"}
PROPERTIES_SECRETS = {"save_path", "download_path", "comment", "created_by", "hash", "name",
                      "infohash_v1", "infohash_v2"}
TRANSFER_SECRETS = {"last_external_address_v4", "last_external_address_v6"}
PEER_SECRETS = {"ip", "port"}

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b")


def out_dir() -> Path:
    # `or`, not a getenv default: .env.example sets QBT_POC_OUT= (empty), which must mean "out".
    return Path(os.getenv("QBT_POC_OUT") or "out") / "samples"


def write_samples(samples: dict[str, Any]) -> Path:
    target = out_dir()
    target.mkdir(parents=True, exist_ok=True)
    for name, data in samples.items():
        (target / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return target


def redact_keys(obj: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    """Replace non-empty values of `keys`; keep everything else (structure and numbers)."""
    return {k: (REDACTED if k in keys and v not in ("", None, -1) else v) for k, v in obj.items()}


def torrents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, t in enumerate(rows, 1):
        clean = redact_keys(t, TORRENT_SECRETS)
        clean["name"] = f"torrent-{i:03d}"
        clean["hash"] = f"{i:040x}"
        out.append(clean)
    return out


def transfer(info: dict[str, Any]) -> dict[str, Any]:
    return redact_keys(info, TRANSFER_SECRETS)


def properties(props: dict[str, Any]) -> dict[str, Any]:
    return redact_keys(props, PROPERTIES_SECRETS)


def files(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, f in enumerate(rows, 1):
        ext = Path(f.get("name", "")).suffix
        out.append({**f, "name": f"file-{i:03d}{ext}"})
    return out


def tracker_host(url: str) -> str:
    """'scheme://host' for real trackers, the URL itself for DHT/PeX/LSD pseudo-rows."""
    if url.startswith("**"):
        return url
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}" if parts.hostname else REDACTED


def trackers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**t, "url": t["url"] if t["url"].startswith("**") else REDACTED,
             "msg": mask_ips(t.get("msg", ""))} for t in rows]


def peers(sync: dict[str, Any]) -> dict[str, Any]:
    clean = dict(sync)
    clean["peers"] = {f"peer-{i:03d}": redact_keys(p, PEER_SECRETS)
                      for i, p in enumerate(sync.get("peers", {}).values(), 1)}
    if "peers_removed" in clean:
        clean["peers_removed"] = [REDACTED for _ in clean["peers_removed"]]
    return clean


def maindata(sync: dict[str, Any]) -> dict[str, Any]:
    clean = dict(sync)
    if "torrents" in sync:
        rows = [{"hash": h, **row} for h, row in sync["torrents"].items()]
        clean["torrents"] = {t["hash"]: {k: v for k, v in t.items() if k != "hash"}
                             for t in torrents(rows)}
    if "torrents_removed" in sync:
        clean["torrents_removed"] = [REDACTED for _ in sync["torrents_removed"]]
    if "server_state" in sync:
        clean["server_state"] = transfer(sync["server_state"])
    return clean


def mask_ips(text: str) -> str:
    return _IPV6.sub("<ip>", _IPV4.sub("<ip>", text or ""))


def log(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**e, "message": REDACTED} for e in entries]
