# maida-qbittorrent-api-poc

Proof of concept for the **qBittorrent WebUI API** (qBittorrent 5.2.x), in Python: a reusable
library, runnable examples, and, in a later stage, an MCP server that runs as a container on a
Synology NAS. Sibling of [maida-synology-api-poc](https://github.com/nsierraj/maida-synology-api-poc).

| Doc | Contents |
| --- | --- |
| [docs/use-cases.md](docs/use-cases.md) | Use cases verified on the real server: calls, parameters, quirks, library method |
| [docs/qbittorrent/webui-api.md](docs/qbittorrent/webui-api.md) | Condensed API reference for the endpoints used here, plus errata against the wiki |
| [docs/qbittorrent/reference-compose.yml](docs/qbittorrent/reference-compose.yml) | How qBittorrent is deployed on the NAS (redacted compose), for networking context |

## Stages

| Stage | Scope | Status |
| --- | --- | --- |
| 0 | Scaffold, CI, docs | done |
| 1 | Discovery, read-only: versions, transfer stats, torrent list, categories, tags | done, verified on the NAS 2026-10-09 |
| 2 | Per-torrent detail: properties, files, trackers, peers, log, sync | built, awaiting real-NAS run |
| 3 | Control inside a sandbox tag: add, stop/start, recheck, category, tags, location, rename, delete | built, awaiting real-NAS run |
| 4 | MCP server over stdio, wired into Claude Code | |
| 5 | HTTP transport, Docker image, Container Manager, reverse proxy | |

## Setup

1. **API key:** qBittorrent WebUI → Tools → Options → Web UI → *API Key* → Generate. Copy the `qbt_…` value.
2. **Sandbox:** write examples only touch torrents tagged `poc` (`QBT_SANDBOX_TAG`), and only save or move data inside `QBT_SANDBOX_SAVEPATH` (a container path, default `/data/torrents/poc`). Anything else is refused locally before a request is sent. `03_lifecycle.py` adds a legal test torrent (`QBT_TEST_MAGNET`, default the Lubuntu 26.04 ISO) and downloads for a few seconds through your VPN.
3. Configure:

```bash
uv sync
cp .env.example .env      # host (NAS LAN IP), port (8090), API key, sandbox tag and save path
```

## Examples

| Example | What it shows | Changes anything? |
| --- | --- | --- |
| `00_probe_auth.py` | How the server treats the API key, Referer/Origin and Host headers. Prints a table for the errata | No |
| `01_discover.py` | Versions, transfer state, WebUI security settings, torrents by state and by filter, categories, tags, fields that differ from the reference. Saves sanitized samples to `out/samples/` | No |
| `02_inspect.py [query]` | One torrent in depth: properties, files, trackers, peers; `sync/maindata` full then delta; the log; fields that differ from the reference. The console hides tracker passkeys and IPs but shows torrent and file names | No |
| `03_lifecycle.py` | Add a test torrent stopped → start briefly → stop → recheck → category → tags → rename → move → a refused change outside the sandbox → delete with files. `--keep` stops before deleting; `--cleanup` removes sandbox leftovers | Only torrents tagged `QBT_SANDBOX_TAG`, inside `QBT_SANDBOX_SAVEPATH` |

```bash
uv run examples/00_probe_auth.py
uv run examples/01_discover.py
uv run examples/02_inspect.py            # newest torrent; or pass part of a name or a hash prefix
uv run examples/03_lifecycle.py          # changes things, but only inside the sandbox
uv run examples/03_lifecycle.py --cleanup
```

**Run the probe once.** It sends one missing and one wrong key on purpose. qBittorrent bans an IP for an hour (Web UI options) after 5 failed attempts by default. Before retrying any example after a 401/403, check `QBT_API_KEY` in `.env`; if you do get locked out, the ban clears when it expires.

## Tests

```bash
uv run pytest
```

The tests run the library and the examples against `tests/fake_qbt.py`, an in-memory qBittorrent. It can't prove the wire format, so a real-NAS run is the final check.

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.11–3.13 for every pull request and push to `main`. It never touches a NAS.

## Code layout

- `src/qbittorrent_poc/client.py`: `QbtClient`, the HTTP layer: API key header, GET/POST, response decoding, errors.
- `src/qbittorrent_poc/webui.py`: `WebUI`, one method per use case. All wire-format knowledge lives here.
- `src/qbittorrent_poc/errors.py`: `QbtError` and the HTTP status meanings.
- `src/qbittorrent_poc/config.py`: loads `.env` and connects with readable failures.
- `src/qbittorrent_poc/policy.py`: `TorrentPolicy`, the sandbox rules (tag, save path, write and delete opt-ins).
- `src/qbittorrent_poc/sandbox.py`: `Sandbox`, policy-checked changes plus waiting and cleanup. Examples and the MCP server change things only through it.
- `src/qbittorrent_poc/fields.py`: reference field sets per endpoint and `diff_fields()`, which the examples use to report what the real server adds or drops.
- `src/qbittorrent_poc/samples.py`: redaction for everything examples save or print.
- `src/qbittorrent_poc/fmt.py`: sizes, speeds, durations and timestamps for humans.
- `tests/fake_qbt.py`: the fake server; `tests/test_*.py`: the suites.
