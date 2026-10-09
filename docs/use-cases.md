# qBittorrent WebUI use cases: catalog and implementation

Every use case this project has proven against the real server: the API calls, parameters, quirks,
the library method that implements it, and (from Stage 4) the MCP tool that exposes it.

- **Target:** qBittorrent 5.2.3, WebAPI 2.15.1, `linuxserver/qbittorrent` behind `gluetun` on the NAS (see [reference-compose.yml](qbittorrent/reference-compose.yml)).
- **API reference:** [qbittorrent/webui-api.md](qbittorrent/webui-api.md). Its Errata section (§8) lists every place where the server differs from the wiki.
- **Implementation:** [`src/qbittorrent_poc/webui.py`](../src/qbittorrent_poc/webui.py) (`WebUI`). The examples in [`examples/`](../examples) and the tests in [`tests/`](../tests) exercise every method.

| ID | Use case | Library method | Example | MCP tool | Safety | Verified on NAS |
| --- | --- | --- | --- | --- | --- | --- |
| UC-01 | Connect, authenticate, versions | `connect()`, `app_version()`, `webapi_version()`, `build_info()` | 00, 01 | – | read | 2026-10-09 |
| UC-02 | Global transfer state | `transfer_info()`, `alt_speed_limits_enabled()`, `default_save_path()` | 01 | – | read | 2026-10-09 |
| UC-03 | List and filter torrents | `list_torrents()` | 01 | – | read | 2026-10-09 |
| UC-04 | Categories and tags | `categories()`, `tags()` | 01 | – | read | 2026-10-09 |
| UC-05 | Find a torrent by name or hash prefix | `find_torrents()`, `resolve_hash()` | 02 | – | read | pending |
| UC-06 | Torrent details: properties, files, trackers | `properties()`, `files()`, `trackers()`, `webseeds()` | 02 | – | read | pending |
| UC-07 | Peers of a torrent | `peers()` | 02 | – | read | pending |
| UC-08 | Incremental sync ("what changed?") | `maindata()` | 02 | – | read | pending |
| UC-09 | Application log | `main_log()` | 02 | – | read | pending |

---

## Cross-cutting rules

1. **API key, not cookies.** Every request carries `Authorization: Bearer qbt_…`. There is no login call; `app/webapiVersion` is the auth probe (`config.connect()`), because keys can't call `auth/login`. A missing or wrong key gets 403. Key requests skip the Referer/Origin check (errata E1, E2).
2. **Errors are HTTP statuses** with a short text body (`Forbidden`, `Unauthorized`, often empty). `QbtError` maps them (`errors.STATUS_MEANINGS`); 401 and 403 are both auth problems.
3. **Response types vary.** JSON for objects and lists; plain text for `app/version`, `app/webapiVersion`, `app/defaultSavePath`, `transfer/speedLimitsMode`. The client decodes by `Content-Type`.
4. **Parameters.** GET query or POST form; booleans are lowercase `true`/`false` (`client.encode`); `hashes` are `|`-joined; tags are comma-separated, and `torrents/info` returns them as one string (`"a, b"`), split with `split_tags()`.
5. **Paths are container paths** (`/data/torrents/...`), never NAS paths.
6. **Never expose secrets in output.** `qbittorrent_poc.samples` redacts what examples save and print: tracker URLs show only `scheme://host` (private trackers put passkeys in the path), peers are summarized without IPs, IPs in log lines are masked, and the external address, names, hashes and paths are dropped from samples. MCP tools follow the same rules.
7. **5.x names.** `stopped` filter, `stoppedDL`/`stoppedUP` states, `torrents/stop`/`start`. `list_torrents("paused")` is refused locally.

---

## UC-01: Connect, authenticate, versions

- **Calls:** `GET app/webapiVersion` (auth probe) → `GET app/version` → `GET app/buildInfo`.
- **Responses:** `"v5.2.3"` and `"2.15.1"` as text; `buildInfo` JSON `{qt, libtorrent, boost, openssl, bitness, …}`.
- **Header checks** (probed by `examples/00_probe_auth.py`, results in errata §8): missing or wrong key → 403; foreign Referer/Origin with a key → 200; `Host: gluetun:8090` → 200.
- **WebUI security settings:** `webui_security_settings()` reads a safe subset of `app/preferences` (host header validation, CSRF, auth bypasses, ban limits). Never return `app/preferences` whole: it holds secrets.
- **Failure handling:** `connect()` exits with a hint for connection errors (host/port) and 401/403 (key, server domains).

## UC-02: Global transfer state

- **Calls:** `GET transfer/info`, `GET transfer/speedLimitsMode` (`"1"`/`"0"` text), `GET app/defaultSavePath`.
- **Fields:** speeds and totals in bytes; rate limits `0` = unlimited; `connection_status` is `connected` | `firewalled` | `disconnected`. With gluetun in front, `firewalled` usually means the VPN has no forwarded port.
- **External address:** `last_external_address_v4`/`_v6` (not on the wiki) is the address peers see; behind gluetun it's the VPN exit IP, a quick "is the VPN up" check. Sensitive: the samples redact it.
- **Observed on the NAS:** alternative speed limits on; `defaultSavePath` is `/data/torrents/completed`.

## UC-03: List and filter torrents

- **Call:** `GET torrents/info` with optional `filter`, `category`, `tag`, `sort`, `reverse`, `limit`, `offset`, `hashes`.
- **Semantics:** `category=""` / `tag=""` select uncategorized / untagged; omitted means any. `offset` may be negative (from the end). `downloading` includes `stoppedDL`; `completed` includes `stoppedUP`.
- **Fields:** 66 on 5.2.3 (`webui.TORRENT_FIELDS`); `private`, not `isPrivate`. Unlimited rate limits are 0.
- **Paging:** the server doesn't return a total. To page, ask for `limit` + 1 and check whether the extra item came back, or count with a separate unlimited call.

## UC-04: Categories and tags

- **Calls:** `GET torrents/categories` → `{name: {name, savePath, download_path, ratio_limit, seeding_time_limit, inactive_seeding_time_limit, share_limit_action}}`; `GET torrents/tags` → `["tag", …]` (`[]` when none).
- **`savePath: ""`** means the category uses the default save path.
- **Counts per category/tag** come from `torrents/info`, not from these endpoints.

## UC-05: Find a torrent by name or hash prefix

- **Calls:** `GET torrents/info` (no search endpoint exists); matching happens in the library.
- **Rules:** an exact hash wins; otherwise a case-insensitive hash prefix or name substring. `resolve_hash()` refuses no match or several matches and lists up to five candidates, which is the behavior an MCP tool needs before acting on a torrent.

## UC-06: Torrent details

- **Calls:** `GET torrents/properties?hash=`, `GET torrents/files?hash=[&indexes=0|2]`, `GET torrents/trackers?hash=`, `GET torrents/webseeds?hash=`.
- **Unknown hash:** 404 per the wiki; `02_inspect.py` [10] checks it on the real server.
- **Files:** priority 0 skip, 1 normal, 6 high, 7 maximal (`fields.FILE_PRIORITIES`). Names are relative paths inside the torrent.
- **Trackers:** the first rows are DHT, PeX and LSD pseudo-trackers (`** [DHT] **`, tier −1). Status 0 disabled, 1 not contacted, 2 working, 3 updating, 4 not working (`fields.TRACKER_STATUSES`). `-1` counts mean unknown.

## UC-07: Peers of a torrent

- **Call:** `GET sync/torrentPeers?hash=&rid=`. The wiki leaves the format as TODO; the reference set is from qBittorrent's source.
- **Shape:** `{rid, full_update, show_flags, peers: {"ip:port": {client, country_code, dl_speed, up_speed, progress, flags, …}}}`. A stopped torrent has no peers.
- **Delta:** passing the previous `rid` returns only changed fields per peer and `peers_removed`.

## UC-08: Incremental sync

- **Call:** `GET sync/maindata?rid=`. `rid=0` (or an unknown rid) returns everything with `full_update: true`: `torrents` keyed by hash (rows without `hash`), `categories`, `tags`, `server_state`.
- **Delta:** with the `rid` from the previous answer, the server returns only what changed: partial torrent rows, `torrents_removed`, new `tags`/`tags_removed`, changed `categories`/`categories_removed`, and changed `server_state` keys. Nothing changed means `{rid}` alone.
- **Why it matters:** one call answers "what changed since I last looked?", which the MCP server can use instead of re-listing everything.
- **`server_state`** extends `transfer/info` with all-time totals, `free_space_on_disk`, `global_ratio`, peer connections and queue/cache stats.

## UC-09: Application log

- **Call:** `GET log/main?normal=&info=&warning=&critical=&last_known_id=`. Entries `{id, message, timestamp, type}`, oldest first; type 1 normal, 2 info, 4 warning, 8 critical (`fields.LOG_TYPES`).
- **Paging:** `last_known_id` returns only newer entries, so a poller keeps the last id it saw.
- **Privacy:** messages can contain IPs (e.g. "Detected external IP") and paths. Mask IPs before showing them; samples drop messages entirely.
