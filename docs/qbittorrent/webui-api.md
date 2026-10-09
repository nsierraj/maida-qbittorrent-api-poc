# qBittorrent WebUI API: condensed reference

The endpoints this project uses, condensed from the official wiki page
[WebUI API (qBittorrent 5.0)](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)),
which covers qBittorrent 5.x. Target server: **qBittorrent 5.2.3, WebAPI 2.15.1**, in a Container Manager
container behind gluetun (see [reference-compose.yml](reference-compose.yml)).

The wiki lags the server in places (it still says `paused` where 5.x says `stopped`). Whenever the real
server disagrees with the wiki, the difference is recorded in [§8 Errata](#8-errata) and the errata win.

## 1. Basics

- Base URL: `http://<host>:<port>/api/v2/<group>/<method>`. Groups: `auth`, `app`, `log`, `sync`, `transfer`, `torrents`, `rss`, `search`.
- GET for reads, POST (form-encoded) for changes. The wrong method gets **405**.
- Responses are JSON unless noted; a few return a plain string (`app/version`) or text (`Ok.`/`Fails.` from `torrents/add`).
- `hashes` parameters take one or more info hashes separated by `|`, or the literal `all`.
- Timestamps are Unix seconds; sizes and speeds are bytes and bytes/s; `-1` means unknown or unlimited.

| HTTP status | Meaning |
| --- | --- |
| 200 | Success |
| 400 | Missing or invalid parameter |
| 403 | Not authenticated, IP banned after failed logins, or no write access (`setLocation`) |
| 404 | Torrent (or search job) not found |
| 405 | Wrong HTTP method |
| 409 | Conflict: unknown category, name already in use, invalid value, feature disabled |
| 415 | Invalid torrent file (`torrents/add`) |

## 2. Authentication

Two mechanisms. This project uses the API key.

**API key (qBittorrent ≥ 5.2.0, WebAPI ≥ 2.14.1).** Generate it in the WebUI: Tools → Options → Web UI → *API Key*.
Send it on every request as `Authorization: Bearer qbt_…`. There is no login round-trip. Keys cannot call
`auth/login`, `auth/logout` or fetch the WebUI's static files. Use `GET app/webapiVersion` as the auth probe.
Not documented on the wiki page; sourced from the 5.2.0 release notes and third-party clients, verified on the
real server in Stage 1 (see Errata).

**Cookie session (all versions).** `POST auth/login` with form fields `username`, `password` returns `Ok.` and a
`SID` cookie, which is sent on later requests; `POST auth/logout` ends it. The IP is banned (403) after too many
failures (`web_ui_max_auth_fail_count`, `web_ui_ban_duration`). Not used here.

**Headers that matter.** The wiki says the `Referer` or `Origin` header must match the `Host` header's domain
and port. qBittorrent also validates the `Host` header ("host header validation" in Web UI options): IP literals
and `localhost` pass; any other hostname must be listed under *Server domains*. On the real server, API key
requests skip the Referer/Origin check, and a container name in `Host` was accepted (Errata E2, E3).

## 3. Application (`app/`)

| Method | Endpoint | Params | Response |
| --- | --- | --- | --- |
| GET | `app/version` | – | string, e.g. `v5.2.3` |
| GET | `app/webapiVersion` | – | string, e.g. `2.15.1` |
| GET | `app/buildInfo` | – | `{qt, libtorrent, boost, openssl: string, bitness: int}` |
| GET | `app/defaultSavePath` | – | string |
| GET | `app/preferences` | – | large settings object. Contains secrets (WebUI password hash, proxy and SMTP passwords): read only, and only the subset in `webui.WEBUI_SECURITY_PREFS` |

Out of scope for this project: `app/setPreferences`, `app/shutdown`, `app/cookies`, `app/setCookies`.

## 4. Transfer (`transfer/`)

| Method | Endpoint | Params | Response |
| --- | --- | --- | --- |
| GET | `transfer/info` | – | object below |
| GET | `transfer/speedLimitsMode` | – | `1` if alternative speed limits are on, else `0` |
| GET | `transfer/downloadLimit`, `transfer/uploadLimit` | – | int bytes/s, `0` = unlimited |

`transfer/info` fields: `dl_info_speed`, `dl_info_data`, `up_info_speed`, `up_info_data`, `dl_rate_limit`,
`up_rate_limit` (ints, bytes or bytes/s), `dht_nodes` (int), `connection_status` (`connected` | `firewalled` |
`disconnected`), and, not on the wiki, `last_external_address_v4` / `_v6`: the public address peers see, which behind
gluetun is the VPN exit IP (treat as sensitive). In `sync/maindata` the same object also carries `queueing`, `use_alt_speed_limits`, `refresh_interval`.

Out of scope: `toggleSpeedLimitsMode`, `setDownloadLimit`, `setUploadLimit`, `banPeers`.

## 5. Torrents: read (`torrents/`)

### 5.1 `GET torrents/info`

| Param | Type | Notes |
| --- | --- | --- |
| `filter` | string | `all`, `downloading`, `seeding`, `completed`, `stopped`, `active`, `inactive`, `running`, `stalled`, `stalled_uploading`, `stalled_downloading`, `errored` |
| `category` | string | Exact category. Empty string = uncategorized. Omitted = any. |
| `tag` | string | Exact tag. Empty string = untagged. Omitted = any. |
| `sort` | string | Any response field name |
| `reverse` | bool | Reverse the sort |
| `limit` | int | Max results |
| `offset` | int | Start offset; negative counts from the end |
| `hashes` | string | `\|`-separated hashes |

Response: array of torrent objects. The 66 fields 5.2.3 actually sends are in `webui.TORRENT_FIELDS`. From the wiki:
`added_on`, `amount_left`, `auto_tmm`, `availability`, `category`, `completed`, `completion_on`, `content_path`,
`dl_limit`, `dlspeed`, `downloaded`, `downloaded_session`, `eta` (8640000 = ∞), `f_l_piece_prio`, `force_start`,
`hash`, `last_activity`, `magnet_uri`, `max_ratio`, `max_seeding_time`, `name`, `num_complete`, `num_incomplete`,
`num_leechs`, `num_seeds`, `priority`, `progress` (0–1), `ratio`, `ratio_limit`, `reannounce`, `save_path`,
`seeding_time`, `seeding_time_limit`, `seen_complete`, `seq_dl`, `size`, `state`, `super_seeding`, `tags`
(comma-separated string), `time_active`, `total_size`, `tracker`, `up_limit`, `uploaded`, `uploaded_session`,
`upspeed`. Not on the wiki: `private` (replaces `isPrivate`), `comment`, `connections_count`, `connections_limit`,
`created_by`, `creation_date`, `download_path`, `has_metadata`, `inactive_seeding_time_limit`, `infohash_v1`,
`infohash_v2`, `max_inactive_seeding_time`, `piece_size`, `pieces_have`, `pieces_num`, `popularity`, `root_path`,
`share_limit_action`, `total_wasted`, `trackers_count`.

**`state` values** (5.x names; the wiki still lists `pausedUP`/`pausedDL`):

| State | Meaning |
| --- | --- |
| `error` | Error |
| `missingFiles` | Data files missing |
| `uploading` | Seeding and transferring |
| `stoppedUP` | Stopped, download finished |
| `queuedUP` | Queued for upload |
| `stalledUP` | Seeding, no connections |
| `checkingUP` | Finished, being checked |
| `forcedUP` | Forced upload, ignores queue |
| `allocating` | Allocating disk space |
| `downloading` | Downloading and transferring |
| `metaDL` | Fetching metadata |
| `stoppedDL` | Stopped, not finished |
| `queuedDL` | Queued for download |
| `stalledDL` | Downloading, no connections |
| `checkingDL` | Checking, not finished |
| `forcedDL` | Forced download, ignores queue |
| `checkingResumeData` | Checking resume data at startup |
| `moving` | Moving to another location |
| `unknown` | Unknown |

### 5.2 Per-torrent detail

| Method | Endpoint | Params | Response |
| --- | --- | --- | --- |
| GET | `torrents/properties` | `hash` | object: `save_path`, `creation_date`, `piece_size`, `comment`, `total_wasted`, `total_uploaded(_session)`, `total_downloaded(_session)`, `up_limit`, `dl_limit`, `time_elapsed`, `seeding_time`, `nb_connections(_limit)`, `share_ratio`, `addition_date`, `completion_date`, `created_by`, `dl_speed(_avg)`, `up_speed(_avg)`, `eta`, `last_seen`, `peers(_total)`, `seeds(_total)`, `pieces_have`, `pieces_num`, `reannounce`, `total_size`, `isPrivate`. 404 if unknown. |
| GET | `torrents/files` | `hash`, optional `indexes` (`\|`-separated) | array of `{index, name, size, progress, priority, is_seed, piece_range: [first, last], availability}`. Priority: 0 skip, 1 normal, 6 high, 7 maximal. |
| GET | `torrents/trackers` | `hash` | array of `{url, status, tier, num_peers, num_seeds, num_leeches, num_downloaded, msg}`. Status: 0 disabled (DHT/PeX/LSD rows, tier < 0), 1 not contacted, 2 working, 3 updating, 4 not working. |
| GET | `torrents/webseeds` | `hash` | array of `{url}` |
| GET | `torrents/pieceStates` | `hash` | array of ints: 0 missing, 1 downloading, 2 have |
| GET | `torrents/categories` | – | object keyed by name: `{name, savePath, download_path, ratio_limit, seeding_time_limit, inactive_seeding_time_limit, share_limit_action}`. `savePath` `""` = default save path |
| GET | `torrents/tags` | – | array of strings |

### 5.3 Sync and log

| Method | Endpoint | Params | Response |
| --- | --- | --- | --- |
| GET | `sync/maindata` | `rid` (int, last response id; omit for a full update) | `{rid, full_update, torrents: {hash: partial torrent}, torrents_removed: [hash], categories, categories_removed, tags, tags_removed, server_state}` |
| GET | `sync/torrentPeers` | `hash`, `rid` | `{rid, full_update, peers: {ip:port: {...}}, peers_removed}` (shape not fully documented) |
| GET | `log/main` | `normal`, `info`, `warning`, `critical` (bool, default true), `last_known_id` (int, default -1) | array of `{id, message, timestamp, type}`; type 1 normal, 2 info, 4 warning, 8 critical |

## 6. Torrents: change (`torrents/`, all POST, form-encoded)

| Endpoint | Params | Status codes |
| --- | --- | --- |
| `torrents/add` | `urls` (newline-separated http/https/magnet URLs) and/or `torrents` (file parts, multipart); optional `savepath`, `category`, `tags` (comma-separated), `skip_checking`, `stopped` (wiki: `paused`), `root_folder`, `rename`, `upLimit`, `dlLimit`, `ratioLimit`, `seedingTimeLimit`, `autoTMM`, `sequentialDownload`, `firstLastPiecePrio`, `contentLayout`, `stopCondition` | 200 with body `Ok.` or `Fails.`; 415 invalid torrent file |
| `torrents/stop` | `hashes` | 200 |
| `torrents/start` | `hashes` | 200 |
| `torrents/recheck` | `hashes` | 200 |
| `torrents/reannounce` | `hashes` | 200 |
| `torrents/delete` | `hashes`, `deleteFiles` (`true`/`false`) | 200 (also for unknown hashes) |
| `torrents/setLocation` | `hashes`, `location` | 400 empty, 403 no write access, 409 cannot create |
| `torrents/rename` | `hash`, `name` | 404 unknown hash, 409 empty name |
| `torrents/setCategory` | `hashes`, `category` (empty string removes) | 409 unknown category |
| `torrents/createCategory` | `category`, `savePath` | 400 empty, 409 invalid |
| `torrents/editCategory` | `category`, `savePath` | 400, 409 |
| `torrents/removeCategories` | `categories` (newline-separated) | 200 |
| `torrents/addTags` | `hashes`, `tags` (comma-separated; created if missing) | 200 |
| `torrents/removeTags` | `hashes`, `tags` (comma-separated; empty = all) | 200 |
| `torrents/createTags` | `tags` | 200 |
| `torrents/deleteTags` | `tags` | 200 |
| `torrents/setDownloadLimit`, `setUploadLimit` | `hashes`, `limit` (bytes/s) | 200 |
| `torrents/setShareLimits` | `hashes`, `ratioLimit`, `seedingTimeLimit`, `inactiveSeedingTimeLimit` (-2 global, -1 none) | 200, 400 |
| `torrents/setForceStart` | `hashes`, `value` | 200 |
| `torrents/setAutoManagement` | `hashes`, `enable` | 200 |
| `torrents/toggleSequentialDownload`, `toggleFirstLastPiecePrio` | `hashes` | 200 |
| `torrents/renameFile`, `renameFolder` | `hash`, `oldPath`, `newPath` | 400, 409 |

Notes for this project: `torrents/add` is sent as multipart with both `stopped` and `paused`; the `hashes`
endpoints answer 200 for unknown hashes, so callers check existence first (`Sandbox`); and changes are
asynchronous, so callers poll `torrents/info` (`Sandbox.wait_for`). Stage 3 records what 5.2.3 actually does.

Out of scope: tracker/peer editing (`addTrackers`, `editTracker`, `removeTrackers`, `addPeers`), queue priority
(`increasePrio` …), `filePrio`, `setSuperSeeding`, RSS, search.

## 7. Version notes

| WebAPI | qBittorrent | Change relevant here |
| --- | --- | --- |
| 2.11 | 5.0 | `torrents/pause` → `stop`, `torrents/resume` → `start`; `paused*` states → `stopped*`; `isPrivate` on `torrents/info` and `properties` (5.2.3's `torrents/info` sends `private` instead, E5) |
| 2.11.3 | 5.0.x | `app/cookies`, `app/setCookies`; `cookie` removed from `torrents/add` |
| 2.14.1 | 5.2.0 | API key authentication (`Authorization: Bearer qbt_…`) |
| 2.15.1 | 5.2.1–5.2.4 | Current target |

## 8. Errata

What the real server (qBittorrent 5.2.3, WebAPI 2.15.1, linuxserver image behind gluetun) does differently from
the wiki. Filled in as each stage runs against it. Each entry: date, endpoint, what the wiki says, what happened,
what the library does.

### Stage 1 (2026-10-09, `examples/00_probe_auth.py` and `01_discover.py`)

| Probe | HTTP | Meaning |
| --- | --- | --- |
| API key, no other headers | 200 | key accepted |
| No key | 403 | auth required (expected) |
| Wrong key | 403 | wrong key refused (expected) |
| Key + matching Referer | 200 | same-origin Referer is fine |
| Key + foreign Referer | 200 | CSRF check skipped for API keys |
| Key + foreign Origin | 200 | CSRF check skipped for API keys |
| Key + Host: gluetun:&lt;port&gt; | 200 | container name accepted |
| Key + POST to a GET endpoint | 200 | GET endpoints also accept POST |

| # | Endpoint | Wiki says | Real server | What the code does |
| --- | --- | --- | --- | --- |
| E1 | any | Login and SID cookie | API key as `Authorization: Bearer qbt_…` works; a missing or wrong key gets **403** `Forbidden` (not 401) | `QbtError.is_auth_error` covers 401 and 403 |
| E2 | any | `Referer`/`Origin` must match `Host` | Not enforced for API key requests: foreign Referer and Origin both get 200 | Client sends neither header; fake skips the check for key requests |
| E3 | any | Names other than IPs/localhost must be in *Server domains* | `Host: gluetun:8090` accepted. Either validation is off or the name is listed; `01_discover.py` [2b] now prints which | Stage 5 can address qBittorrent as `gluetun` on `synobridge`; fake accepts names unless `host_header_validation=True` |
| E4 | any | Wrong method gets 405 | POST to a GET endpoint (`app/version`) gets 200. GET on a POST-only endpoint not yet probed (Stage 3) | Client always uses the documented method; fake refuses GET on POST-only endpoints, per qBittorrent's source |
| E5 | `torrents/info` | `isPrivate` field | No `isPrivate`; sends `private` | `TORRENT_FIELDS` is the real 5.2.3 list |
| E6 | `torrents/info` | 46 fields | 66 fields: 20 more (see §5.1) | Same |
| E7 | `torrents/info` | `dl_limit`/`up_limit` −1 = unlimited | 0 for a torrent without a limit | `fmt.limit()` treats 0 and −1 as unlimited |
| E8 | `transfer/info` | 8 fields | Also `last_external_address_v4` / `_v6`, the public (VPN exit) address | Shown on screen, redacted in samples |
| E9 | `torrents/categories` | `{name, savePath}` | Also `download_path` (null), `ratio_limit`, `seeding_time_limit`, `inactive_seeding_time_limit` (−2 = global), `share_limit_action` (`Default`); `savePath` `""` = default save path | Fake uses the real shape |
| E10 | `app/buildInfo` | `qt`, `libtorrent`, `boost`, `openssl`, `bitness` | Also `platform`, `zlib` | – |
