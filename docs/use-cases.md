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
| UC-05 | Find a torrent by name or hash prefix | `find_torrents()`, `resolve_hash()` | 02 | – | read | 2026-10-09 |
| UC-06 | Torrent details: properties, files, trackers | `properties()`, `files()`, `trackers()`, `webseeds()` | 02 | – | read | 2026-10-09 |
| UC-07 | Peers of a torrent | `peers()` | 02 | – | read | 2026-10-09 |
| UC-08 | Incremental sync ("what changed?") | `maindata()` | 02 | – | read | 2026-10-09 |
| UC-09 | Application log | `main_log()` | 02 | – | read | 2026-10-09 |
| UC-10 | Add a torrent (magnet/URL) | `Sandbox.add()` → `add()` | 03 | – | write | 2026-10-09 |
| UC-11 | Stop, start, recheck, reannounce | `Sandbox.stop/start/recheck/reannounce()` | 03 | – | write | 2026-10-09 |
| UC-12 | Categories | `Sandbox.ensure_category/set_category()` | 03 | – | write | 2026-10-09 |
| UC-13 | Tags | `Sandbox.add_tags/remove_tags()` | 03 | – | write | 2026-10-09 |
| UC-14 | Rename and move | `Sandbox.rename/set_location()` | 03 | – | write | 2026-10-09 |
| UC-15 | Delete (optionally with data) | `Sandbox.delete/cleanup()` | 03 | – | destructive | 2026-10-09 |

---

## Cross-cutting rules

1. **API key, not cookies.** Every request carries `Authorization: Bearer qbt_…`. There is no login call; `app/webapiVersion` is the auth probe (`config.connect()`), because keys can't call `auth/login`. A missing or wrong key gets 403. Key requests skip the Referer/Origin check (errata E1, E2).
2. **Errors are HTTP statuses** with a short text body (`Forbidden`, `Unauthorized`, often empty). `QbtError` maps them (`errors.STATUS_MEANINGS`); 401 and 403 are both auth problems.
3. **Response types vary.** JSON for objects and lists; plain text for `app/version`, `app/webapiVersion`, `app/defaultSavePath`, `transfer/speedLimitsMode`. The client decodes by `Content-Type`.
4. **Parameters.** GET query or POST form; booleans are lowercase `true`/`false` (`client.encode`); `hashes` are `|`-joined; tags are comma-separated, and `torrents/info` returns them as one string (`"a, b"`), split with `split_tags()`.
5. **Paths are container paths** (`/data/torrents/...`), never NAS paths.
6. **Never expose secrets in output.** `qbittorrent_poc.samples` redacts what examples save and print: tracker URLs show only `scheme://host` (private trackers put passkeys in the path), peers are summarized without IPs, IPs in log lines are masked, and the external address, names, hashes and paths are dropped from samples. MCP tools follow the same rules.
7. **Changes only through the sandbox.** `Sandbox` checks `TorrentPolicy` before sending anything: the torrents must exist and carry the sandbox tag (`all` is refused, a mixed batch is refused whole), the sandbox tag can't be removed, save paths and moves stay inside the sandbox path, and writes and deletes are separate opt-ins. A `PolicyError` means no request was sent.
8. **Changes are asynchronous.** The server answers before the change is visible: an added magnet appears a moment later, a stop or move takes time. `Sandbox.wait_for()` polls `torrents/info` until a condition holds.
9. **5.x names.** `stopped` filter, `stoppedDL`/`stoppedUP` states, `torrents/stop`/`start`. `list_torrents("paused")` is refused locally.

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

- **Call:** `GET sync/torrentPeers?hash=&rid=`. The wiki leaves the format as TODO; `fields.PEER_FIELDS` is the real 5.2.3 set (E20), including `host_name` (reverse DNS, identifying: redact like the IP).
- **Shape:** `{rid, full_update, show_flags, peers: {"ip:port": {client, country_code, dl_speed, up_speed, progress, flags, …}}}`. A stopped torrent has no peers.
- **Delta:** passing the previous `rid` returns only changed fields per peer and `peers_removed`.

## UC-08: Incremental sync

- **Call:** `GET sync/maindata?rid=`. `rid=0` (or an unknown rid) returns everything with `full_update: true`: `torrents` keyed by hash (rows without `hash`), `categories`, `tags`, `server_state`.
- **Delta:** with the `rid` from the previous answer, the server returns only what changed: partial torrent rows, `torrents_removed`, new `tags`/`tags_removed`, changed `categories`/`categories_removed`, and changed `server_state` keys. Nothing changed means `{rid}` alone.
- **Why it matters:** one call answers "what changed since I last looked?", which the MCP server can use instead of re-listing everything.
- **Rows** are keyed by hash and carry three tracker-health flags `torrents/info` doesn't (E19).
- **`server_state`** (26 keys, E18) extends `transfer/info` with all-time totals, `free_space_on_disk`, `global_ratio`, peer connections and queue/cache stats.

## UC-09: Application log

- **Call:** `GET log/main?normal=&info=&warning=&critical=&last_known_id=`. Entries `{id, message, timestamp, type}`, oldest first; type 1 normal, 2 info, 4 warning, 8 critical (`fields.LOG_TYPES`).
- **Paging:** `last_known_id` returns only newer entries, so a poller keeps the last id it saw.
- **Privacy:** messages can contain IPs, paths and the user's search-engine queries. Mask IPs before showing them; samples drop messages entirely.

## UC-10: Add a torrent

- **Call:** `POST torrents/add` (multipart): `urls` (newline-separated magnet/http links), `savepath`, `category`, `tags` (comma-separated), `stopped`, `rename`, `sequentialDownload`, `skip_checking`.
- **Stopped on add:** 5.x renamed `paused` to `stopped`; the library sends both. `03_lifecycle.py` reports whether the new torrent arrived stopped, and stops it at once if not.
- **Answer (E11):** 5.2.3 answers JSON `{added_torrent_ids, success_count, pending_count, failure_count}`; a `.torrent` URL is `pending` because the server fetches it afterwards. Older servers answer `Ok.`/`Fails.`. `add()` raises `QbtError` 409 when nothing was added.
- **Settling (E12):** a new torrent may show `checkingResumeData` first; wait for it to settle before judging its state.
- **Incomplete-downloads folder (E16):** with "keep incomplete torrents in" on, data goes to `download_path` whatever `savepath` says. `Sandbox.add()` sends `useDownloadPath=false`, and `TorrentPolicy.check_row()` verifies both paths after adding.
- **Knowing the hash first:** `torrents/add` answers before the torrent exists, and for a URL before qBittorrent has even fetched the `.torrent` file. The sandbox needs the hash up front (to refuse a torrent already present outside it, then to find the new one), so: for a magnet it comes from the link (`magnet_hash()`, hex or base32); for a `.torrent` URL, `03_lifecycle.py` fetches the file itself and hashes the info dictionary (`torrentfile.parse()`: SHA-1, or truncated SHA-256 for v2-only). qBittorrent then fetches the URL again to add it.
- **Magnets:** until metadata arrives the torrent has `has_metadata: false`, size 0 and state `metaDL` (running) or `stoppedDL`.
- **Automatic Torrent Management:** with it on (per request or the server's `auto_tmm_enabled`), qBittorrent ignores `savepath`. `add()` always sends `autoTMM=false`, and `03_lifecycle.py` checks where the torrent actually landed.
- **Sandbox:** `Sandbox.add()` always adds the sandbox tag and requires the save path to be inside the sandbox path.

## UC-11: Stop, start, recheck, reannounce

- **Calls:** `POST torrents/stop|start|recheck|reannounce` with `hashes`. 200 even for unknown hashes, so the sandbox checks existence first.
- **Recheck (E15):** a stopped torrent goes `checkingDL` → `stoppedDL` on 5.2.3 (not resumed). While checking, `progress` is the check's progress; use `completed`/`pieces_have`. Some older versions resumed after a recheck; the example stops it again if so.
- **Start/stop (E14):** start passes through `stalledDL`/`queuedDL`; stop takes a moment.
- **Method (E13):** POST-only, enforced: GET gets 405.

## UC-12: Categories

- **Calls:** `POST torrents/createCategory` (`category`, `savePath`; 409 if it exists or is invalid), `POST torrents/setCategory` (`hashes`, `category`; 409 for an unknown category, `""` removes it), `POST torrents/removeCategories` (newline-separated names; their torrents become uncategorized).
- **Sandbox:** `ensure_category()` creates the category only if missing, with a save path inside the sandbox; cleanup removes it only when no torrent uses it.

## UC-13: Tags

- **Calls:** `POST torrents/addTags` (creates missing tags), `POST torrents/removeTags` (an empty list would remove every tag, so `remove_tags()` refuses it), `POST torrents/deleteTags` (removes tags from qBittorrent and every torrent).
- **Sandbox:** the sandbox tag can't be removed; otherwise a torrent could leave the sandbox. Tags come back sorted, as one comma-separated string.

## UC-14: Rename and move

- **Calls:** `POST torrents/rename` (`hash`, `name`; display name only, files keep their names; 404 unknown hash, 409 empty name), `POST torrents/setLocation` (`hashes`, `location`; 400 empty, 403 no write access, 409 can't create the folder).
- **Moves are asynchronous** (state `moving`); wait until `save_path` changes.
- **Sandbox:** the target must be inside the sandbox path.

## UC-15: Delete

- **Call:** `POST torrents/delete` (`hashes`, `deleteFiles`). 200 even for unknown hashes. `delete()` has no default for `delete_files`, so every caller decides.
- **Sandbox:** needs the separate delete opt-in. `cleanup()` deletes every sandbox torrent, waits until they're gone, then removes helper tags and unused sandbox categories.
