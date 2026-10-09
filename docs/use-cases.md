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

---

## Cross-cutting rules

1. **API key, not cookies.** Every request carries `Authorization: Bearer qbt_…`. There is no login call; `app/webapiVersion` is the auth probe (`config.connect()`), because keys can't call `auth/login`. A missing or wrong key gets 403. Key requests skip the Referer/Origin check (errata E1, E2).
2. **Errors are HTTP statuses** with a short text body (`Forbidden`, `Unauthorized`, often empty). `QbtError` maps them (`errors.STATUS_MEANINGS`); 401 and 403 are both auth problems.
3. **Response types vary.** JSON for objects and lists; plain text for `app/version`, `app/webapiVersion`, `app/defaultSavePath`, `transfer/speedLimitsMode`. The client decodes by `Content-Type`.
4. **Parameters.** GET query or POST form; booleans are lowercase `true`/`false` (`client.encode`); `hashes` are `|`-joined; tags are comma-separated, and `torrents/info` returns them as one string (`"a, b"`), split with `split_tags()`.
5. **Paths are container paths** (`/data/torrents/...`), never NAS paths.
6. **5.x names.** `stopped` filter, `stoppedDL`/`stoppedUP` states, `torrents/stop`/`start`. `list_torrents("paused")` is refused locally.

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
