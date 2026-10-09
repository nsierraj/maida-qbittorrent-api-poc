# maida-qbittorrent-api-poc

Proof of concept for the **qBittorrent WebUI API** (qBittorrent 5.2.x), in Python: a reusable
library, runnable examples, and, in a later stage, an MCP server that runs as a container on a
Synology NAS. Sibling of [maida-synology-api-poc](https://github.com/nsierraj/maida-synology-api-poc).

| Doc | Contents |
| --- | --- |
| [docs/qbittorrent/webui-api.md](docs/qbittorrent/webui-api.md) | Condensed API reference for the endpoints used here, plus errata against the wiki |
| [docs/qbittorrent/reference-compose.yml](docs/qbittorrent/reference-compose.yml) | How qBittorrent is deployed on the NAS (redacted compose), for networking context |

## Stages

| Stage | Scope | Status |
| --- | --- | --- |
| 0 | Scaffold, CI, docs | done |
| 1 | Discovery, read-only: versions, transfer stats, torrent list, categories, tags | next |
| 2 | Per-torrent detail: properties, files, trackers, peers, log, sync | |
| 3 | Control inside a sandbox tag: add, stop/start, recheck, category, tags, location, rename, delete | |
| 4 | MCP server over stdio, wired into Claude Code | |
| 5 | HTTP transport, Docker image, Container Manager, reverse proxy | |

## Setup

1. **API key:** qBittorrent WebUI → Tools → Options → Web UI → *API Key* → Generate. Copy the `qbt_…` value.
2. **Sandbox tag:** write examples only touch torrents tagged `poc` (`QBT_SANDBOX_TAG`). Nothing else is modified.
3. Configure:

```bash
uv sync
cp .env.example .env      # host (NAS LAN IP), port (8090), API key, sandbox tag and save path
```

## Tests

```bash
uv run pytest
```

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.11–3.13 for every pull request and push to `main`. It never touches a NAS.
