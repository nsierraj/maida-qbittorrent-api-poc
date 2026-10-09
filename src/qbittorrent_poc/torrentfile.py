"""Read just enough of a .torrent file to know which torrent it is before adding it.

qBittorrent identifies a torrent by its info hash: SHA-1 of the bencoded `info` dictionary for
v1 and hybrid torrents, and the first 40 hex digits of its SHA-256 for v2-only torrents. Knowing
it up front lets the sandbox refuse a torrent that already exists outside it, and find the new
one after torrents/add (which answers before the torrent appears).
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

MAX_TORRENT_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5


class TorrentFileError(ValueError):
    """The bytes aren't a usable .torrent file."""


def _decode(data: bytes, i: int, spans: dict[str, tuple[int, int]], depth: int = 0) -> tuple[Any, int]:
    if depth > 64:
        raise TorrentFileError("Nested too deeply.")
    if i >= len(data):
        raise TorrentFileError("Truncated data.")
    c = data[i:i + 1]
    if c == b"i":
        end = data.index(b"e", i)
        return int(data[i + 1:end]), end + 1
    if c == b"l":
        i += 1
        items = []
        while data[i:i + 1] != b"e":
            value, i = _decode(data, i, spans, depth + 1)
            items.append(value)
        return items, i + 1
    if c == b"d":
        i += 1
        out: dict[bytes, Any] = {}
        while data[i:i + 1] != b"e":
            key, i = _decode(data, i, spans, depth + 1)
            if not isinstance(key, bytes):
                raise TorrentFileError("Dictionary keys must be strings.")
            start = i
            value, i = _decode(data, i, spans, depth + 1)
            if key == b"info" and depth == 0:
                spans["info"] = (start, i)
            out[key] = value
        return out, i + 1
    if c.isdigit():
        colon = data.index(b":", i)
        length = int(data[i:colon])
        start = colon + 1
        if start + length > len(data):
            raise TorrentFileError("Truncated string.")
        return data[start:start + length], start + length
    raise TorrentFileError(f"Unexpected byte {c!r} at {i}.")


def encode(value: Any) -> bytes:
    """Bencode a value (ints, bytes/str, lists, dicts with sorted keys). Used to build test data."""
    if isinstance(value, bool):
        raise TypeError("bencode has no booleans")
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(encode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
        return b"d" + b"".join(encode(k) + encode(v) for k, v in items) + b"e"
    raise TypeError(f"can't bencode {type(value).__name__}")


@dataclass(frozen=True)
class TorrentFile:
    info_hash: str  # what qBittorrent calls `hash`
    name: str
    size: int | None  # total payload bytes; None for v2-only file trees
    webseeds: tuple[str, ...]
    raw: bytes = field(default=b"", repr=False)  # the file itself, for uploading to qBittorrent


def parse(data: bytes) -> TorrentFile:
    if len(data) > MAX_TORRENT_BYTES:
        raise TorrentFileError("Larger than any sensible .torrent file.")
    spans: dict[str, tuple[int, int]] = {}
    try:
        meta, end = _decode(data, 0, spans)
    except (ValueError, IndexError) as e:
        raise TorrentFileError(f"Not a .torrent file: {e}") from e
    if not isinstance(meta, dict) or "info" not in spans or not isinstance(meta.get(b"info"), dict):
        raise TorrentFileError("Not a .torrent file: no info dictionary.")
    info = meta[b"info"]
    raw_info = data[spans["info"][0]:spans["info"][1]]
    v2_only = info.get(b"meta version") == 2 and b"pieces" not in info
    info_hash = hashlib.sha256(raw_info).hexdigest()[:40] if v2_only else hashlib.sha1(raw_info).hexdigest()
    if b"length" in info:
        size: int | None = info[b"length"]
    elif isinstance(info.get(b"files"), list):
        size = sum(f.get(b"length", 0) for f in info[b"files"])
    else:
        size = None
    seeds = meta.get(b"url-list", [])
    seeds = [seeds] if isinstance(seeds, bytes) else seeds
    return TorrentFile(
        info_hash=info_hash,
        name=info.get(b"name", b"").decode("utf-8", "replace"),
        size=size,
        webseeds=tuple(s.decode("utf-8", "replace") for s in seeds if isinstance(s, bytes)),
        raw=data,
    )


def _resolve(host: str, port: int) -> list[str]:
    """Every address `host` resolves to (patched in tests)."""
    return sorted({info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)})


def check_public_url(url: str) -> None:
    """Refuse URLs that aren't http(s) or whose host resolves to a non-public address.

    Whoever runs the fetch (the MCP server inside the NAS, typically) could otherwise be pointed
    at DSM, the LAN, a container's control port or cloud metadata endpoints (SSRF). Every address
    the name resolves to must be globally routable. A name that re-resolves differently between
    this check and the connection (DNS rebinding) isn't covered; the file is only ever parsed as
    bencode, and qBittorrent is handed the bytes, never the URL.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise TorrentFileError("Only http(s) URLs of .torrent files can be fetched.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        ipaddress.ip_address(parts.hostname.split("%")[0])
        literal = True
    except ValueError:
        literal = False
    try:
        addresses = [parts.hostname] if literal else _resolve(parts.hostname, port)
    except (socket.gaierror, UnicodeError) as e:
        raise TorrentFileError(f"Can't resolve {parts.hostname}: {e}") from e
    if not addresses:
        raise TorrentFileError(f"Can't resolve {parts.hostname}.")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise TorrentFileError(
                f"Refused: {parts.hostname} resolves to {ip}, a private or internal address. "
                "Only public http(s) URLs of .torrent files are fetched."
            )


def fetch(url: str, *, timeout: float = 30) -> TorrentFile:
    """Download a .torrent file from a public http(s) URL (at most MAX_TORRENT_BYTES) and parse it.
    Redirects are followed by hand so that every hop passes check_public_url()."""
    import requests

    for _ in range(MAX_REDIRECTS + 1):
        check_public_url(url)
        try:
            with requests.get(url, timeout=timeout, stream=True, allow_redirects=False) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                    url = urljoin(url, resp.headers["Location"])
                    continue
                resp.raise_for_status()
                data = b""
                for chunk in resp.iter_content(64 * 1024):
                    data += chunk
                    if len(data) > MAX_TORRENT_BYTES:
                        raise TorrentFileError("Larger than any sensible .torrent file.")
        except requests.RequestException as e:
            raise TorrentFileError(f"Couldn't download {url}: {e}") from e
        return parse(data)
    raise TorrentFileError(f"More than {MAX_REDIRECTS} redirects.")


def identify(source: str) -> tuple[str, str, TorrentFile | None]:
    """(info hash, display name, parsed file or None) for a magnet link or a .torrent URL, before
    adding it: torrents/add answers before the torrent exists, so callers need the hash first."""
    from urllib.parse import parse_qs

    from .webui import magnet_hash

    source = source.strip()
    if source.startswith("magnet:"):
        h = magnet_hash(source)
        names = parse_qs(urlsplit(source).query).get("dn", [])
        return h, names[0] if names else h, None
    if source.startswith(("http://", "https://")):
        meta = fetch(source)
        return meta.info_hash, meta.name, meta
    raise TorrentFileError("Give a magnet link or an http(s) URL of a .torrent file.")
