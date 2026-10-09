# Changelog

All notable changes are recorded here, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
The project follows [Semantic Versioning](https://semver.org/); while it is 0.x, minor releases may change behavior.

## [Unreleased]

### Added
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
- Verified Stage 1 against the real server (qBittorrent 5.2.3, WebAPI 2.15.1). Findings are in `docs/qbittorrent/webui-api.md` §8 (errata E1–E10): API keys skip the Referer/Origin check, a container name in `Host` is accepted, GET endpoints accept POST, and `torrents/info` sends 66 fields including `private` instead of `isPrivate`.
- `TORRENT_FIELDS` is now the real 5.2.3 field list; `tests/fake_qbt.py` follows the observed behavior, field set, defaults and category shape.
- `examples/00_probe_auth.py` describes the observed results more precisely.

### Fixed
- `examples/01_discover.py` wrote its samples to `samples/` in the current folder, not to `out/`, when `.env` had an empty `QBT_POC_OUT=` (as `.env.example` does). An empty value now means `out`.
- `examples/01_discover.py` saved the server's external address (`last_external_address_v4`/`_v6`, the VPN exit IP) unredacted in `transfer_info.json`.
