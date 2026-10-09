# Changelog

All notable changes are recorded here, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
The project follows [Semantic Versioning](https://semver.org/); while it is 0.x, minor releases may change behavior.

## [Unreleased]

### Added
- `qbittorrent_poc.torrentfile`: reads a `.torrent` file's info hash (SHA-1 of the info dictionary; truncated SHA-256 for v2-only), name, size and web seeds, so a torrent added by URL can be identified before it appears. Verified against the hash Arch Linux publishes for 2026.10.01.
- Stage 3, changes inside a sandbox: raw `WebUI` writes (`add`, `stop`, `start`, `recheck`, `reannounce`, categories, tags, `rename`, `set_location`, `delete`) and `magnet_hash()`.
- `TorrentPolicy` and `Sandbox`: every change is refused locally unless the torrents carry the sandbox tag and paths stay inside the sandbox save path; writes and deletes are separate opt-ins; `add` always applies the tag; `wait_for()` and `cleanup()`. `add()` always sends `autoTMM=false`, because Automatic Torrent Management would otherwise ignore the save path.
- `examples/03_lifecycle.py`: add a legal test torrent stopped (`QBT_TEST_TORRENT`, a `.torrent` URL or a magnet link; default the Arch Linux 2026.10.01 ISO), start briefly, stop, recheck, categorize, tag, rename, move, show a refused change outside the sandbox, delete with files. `--keep` and `--cleanup`.
- The fake serves the Stage 3 endpoints. UC-10 to UC-15 in `docs/use-cases.md`.
- Stage 2, per-torrent detail (read-only): `WebUI.find_torrents()`/`resolve_hash()` (name substring or hash prefix), `properties()`, `files()`, `trackers()`, `webseeds()`, `peers()` (`sync/torrentPeers`), `maindata()` (`sync/maindata`, full and incremental) and `main_log()`.
- `qbittorrent_poc.fields`: reference field sets per endpoint, status and priority names, and `diff_fields()`.
- `qbittorrent_poc.samples`: one place for redaction of everything examples print or save (tracker passkeys, peer and external IPs, log messages, names, hashes, paths).
- `examples/02_inspect.py`: one torrent in depth, a full and a delta `sync/maindata`, the log, and fields that differ from the reference; output is safe to paste.
- The fake server serves the Stage 2 endpoints, including sync deltas by `rid`. UC-05 to UC-09 in `docs/use-cases.md`.
- `WebUI.webui_security_settings()`: host header validation, CSRF, auth bypass and ban settings from `app/preferences`, never the secrets that endpoint also holds. `01_discover.py` prints them, plus the external address.
- `qbittorrent_poc` library, Stage 1 (read-only): `QbtClient` with API key auth (`Authorization: Bearer`), `QbtError`, `Settings`/`connect()` with readable setup errors, and `WebUI` with versions, build info, transfer state, alternative speed limits, default save path, `list_torrents()` (filter, category, tag, sort, limit, offset, hashes), categories and tags.
- `fmt` helpers for sizes, speeds, durations and timestamps.
- `examples/00_probe_auth.py`: probes how the server treats the API key and the Referer/Origin/Host checks. `examples/01_discover.py`: a read-only tour that also reports fields and states the wiki doesn't list and saves sanitized samples.
- `tests/fake_qbt.py`, an in-memory qBittorrent 5.x, and tests for the client, `WebUI`, config, formatting and both examples.
- `docs/use-cases.md`, UC-01 to UC-04.
- Project scaffold mirroring `maida-synology-api-poc`: `uv` project, CI on Python 3.11–3.13, Dependabot, `.env.example`, `CLAUDE.md`.
- `docs/qbittorrent/webui-api.md`: condensed WebUI API reference for the endpoints this project uses, with an Errata section for what the real server does differently from the wiki.
- `docs/qbittorrent/reference-compose.yml`: redacted copy of the qBittorrent + gluetun compose project on the NAS, for networking context.

### Changed
- Verified Stages 2 and 3 on the real server (errata E11–E21). The fake now follows it:
  - `torrents/add` answers JSON, and `.torrent` URLs are pending.
  - New torrents pass through `checkingResumeData`, and a recheck goes through `checkingDL`.
  - `torrents/properties` has 44 fields, the `server_state` 26 keys, and sync rows three tracker flags.
  - Peers have 17 fields, including `host_name`.
- `fields.PROPERTIES_FIELDS`, `SERVER_STATE_FIELDS`, `PEER_FIELDS` and the new `MAINDATA_TORRENT_FIELDS` are the real 5.2.3 sets. `02_inspect.py` also compares `torrents/info` and sync rows.
- `03_lifecycle.py` waits for a new torrent's state to settle before judging stop-on-add, and waits for a recheck to finish.
- `examples/02_inspect.py` and the README no longer call the console output "safe to paste": tracker passkeys and IPs are hidden, but torrent names, file names and log messages are shown.
- Verified Stage 1 against the real server (qBittorrent 5.2.3, WebAPI 2.15.1). Findings are in `docs/qbittorrent/webui-api.md` §8 (errata E1–E10): API keys skip the Referer/Origin check, a container name in `Host` is accepted, GET endpoints accept POST, and `torrents/info` sends 66 fields including `private` instead of `isPrivate`.
- `TORRENT_FIELDS` is now the real 5.2.3 field list; `tests/fake_qbt.py` follows the observed behavior, field set, defaults and category shape.
- `examples/00_probe_auth.py` describes the observed results more precisely.

### Fixed
- Sandbox data could land outside the sandbox. With "keep incomplete torrents in" enabled on the server, incomplete data went to its folder, not `savepath`. `Sandbox.add()` now sends `useDownloadPath=false`, and `TorrentPolicy.check_row()` checks both `save_path` and `download_path`. `03_lifecycle.py` deletes a torrent the server put outside the sandbox before downloading anything.
- Samples now also redact peers' `host_name`.
- `examples/01_discover.py` wrote its samples to `samples/` in the current folder, not to `out/`, when `.env` had an empty `QBT_POC_OUT=` (as `.env.example` does). An empty value now means `out`.
- `examples/01_discover.py` saved the server's external address (`last_external_address_v4`/`_v6`, the VPN exit IP) unredacted in `transfer_info.json`.
