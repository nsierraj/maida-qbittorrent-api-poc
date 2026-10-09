# qBittorrent WebUI use cases: catalog and implementation

Every use case this project has proven against the real server: the API calls, parameters, quirks,
the library method that implements it, and (from Stage 4) the MCP tool that exposes it.

- **Target:** qBittorrent 5.2.3, WebAPI 2.15.1, `linuxserver/qbittorrent` behind `gluetun` on the NAS (see [reference-compose.yml](qbittorrent/reference-compose.yml)).
- **API reference:** [qbittorrent/webui-api.md](qbittorrent/webui-api.md). Its Errata section (§8) lists every place where the server differs from the wiki.
- **Implementation:** [`src/qbittorrent_poc/webui.py`](../src/qbittorrent_poc/webui.py) (`WebUI`). The examples in [`examples/`](../examples) and the tests in [`tests/`](../tests) exercise every method.

| ID | Use case | Library method | Example | MCP tool | Safety | Verified on NAS |
| --- | --- | --- | --- | --- | --- | --- |
| UC-01 | Connect, authenticate, versions | `connect()`, `app_version()`, `webapi_version()`, `build_info()` | 00, 01 | – | read | pending |
| UC-02 | Global transfer state | `transfer_info()`, `alt_speed_limits_enabled()`, `default_save_path()` | 01 | – | read | pending |
| UC-03 | List and filter torrents | `list_torrents()` | 01 | – | read | pending |
| UC-04 | Categories and tags | `categories()`, `tags()` | 01 | – | read | pending |

---

## Cross-cutting rules

1. **API key, not cookies.** Every request carries `Authorization: Bearer qbt_…`. There is no login call; `app/webapiVersion` is the auth probe (`config.connect()`), because keys can't call `auth/login`.
2. **Errors are HTTP statuses** with a short text body (`Forbidden`, `Unauthorized`, often empty). `QbtError` maps them (`errors.STATUS_MEANINGS`); 401 and 403 are both auth problems.
3. **Response types vary.** JSON for objects and lists; plain text for `app/version`, `app/webapiVersion`, `app/defaultSavePath`, `transfer/speedLimitsMode`. The client decodes by `Content-Type`.
4. **Parameters.** GET query or POST form; booleans are lowercase `true`/`false` (`client.encode`); `hashes` are `|`-joined; tags are comma-separated, and `torrents/info` returns them as one string (`"a, b"`), split with `split_tags()`.
5. **Paths are container paths** (`/data/torrents/...`), never NAS paths.
6. **5.x names.** `stopped` filter, `stoppedDL`/`stoppedUP` states, `torrents/stop`/`start`. `list_torrents("paused")` is refused locally.

---

## UC-01: Connect, authenticate, versions

- **Calls:** `GET app/webapiVersion` (auth probe) → `GET app/version` → `GET app/buildInfo`.
- **Responses:** `"v5.2.3"` and `"2.15.1"` as text; `buildInfo` JSON `{qt, libtorrent, boost, openssl, bitness, …}`.
- **Header checks** (probed by `examples/00_probe_auth.py`): missing or wrong key, cross-site Referer/Origin, and a `Host` that isn't an IP or a listed server domain. Results go in errata §8.
- **Failure handling:** `connect()` exits with a hint for connection errors (host/port) and 401/403 (key, server domains).

## UC-02: Global transfer state

- **Calls:** `GET transfer/info`, `GET transfer/speedLimitsMode` (`"1"`/`"0"` text), `GET app/defaultSavePath`.
- **Fields:** speeds and totals in bytes; rate limits `0` = unlimited; `connection_status` is `connected` | `firewalled` | `disconnected`. With gluetun in front, `firewalled` usually means the VPN has no forwarded port.

## UC-03: List and filter torrents

- **Call:** `GET torrents/info` with optional `filter`, `category`, `tag`, `sort`, `reverse`, `limit`, `offset`, `hashes`.
- **Semantics:** `category=""` / `tag=""` select uncategorized / untagged; omitted means any. `offset` may be negative (from the end). `downloading` includes `stoppedDL`; `completed` includes `stoppedUP`.
- **Paging:** the server doesn't return a total. To page, ask for `limit` + 1 and check whether the extra item came back, or count with a separate unlimited call.

## UC-04: Categories and tags

- **Calls:** `GET torrents/categories` → `{name: {name, savePath}}`; `GET torrents/tags` → `["tag", …]`.
- **Counts per category/tag** come from `torrents/info`, not from these endpoints.
