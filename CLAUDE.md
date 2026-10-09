# maida-qbittorrent-api-poc

Python library, examples and (later) an MCP server for the qBittorrent WebUI API (qBittorrent 5.2.x, WebAPI 2.15), verified against the user's real NAS. Sibling of `maida-synology-api-poc`, which this repo mirrors in structure and workflow.

## Commands

- `uv sync`: install (Python 3.11–3.13; `.python-version` pins 3.13 to match CI and the container image)
- `uv run pytest`: the whole suite, against the fake qBittorrent. Must pass before any commit. CI runs it on Python 3.11–3.13.
- `uv run examples/0N_*.py`: real-NAS runs. They need `.env` and are run by the user. Write examples only touch torrents tagged `QBT_SANDBOX_TAG`.

## Code

- `src/qbittorrent_poc/`: the library (client, API methods, policy, config). All wire-format knowledge lives here.
- `src/qbittorrent_mcp/`: the MCP server (added in a later stage).
- `examples/`: numbered scripts run by hand against the real NAS.
- `tests/`: `fake_qbt.py` is an in-memory qBittorrent; when you learn a new quirk on the real server, add it to the fake and add a test.
- `docs/qbittorrent/webui-api.md`: condensed API reference with an Errata section. Read it first.

## Rules that aren't obvious from the code

- **All changes go through a pull request**, never a direct push to `main`. CI (`.github/workflows/ci.yml`) must be green. Workflows must not use secrets, `.env` or a real NAS.
- **The wiki lags the server.** The official wiki page is for 5.0 and still says `paused` in places; qBittorrent 5.x uses `torrents/stop`, `torrents/start`, the `stopped` filter and `stoppedDL`/`stoppedUP` states. When the wiki and the real server disagree, trust `docs/qbittorrent/webui-api.md` §Errata, and record what the server did. If an operation fails, capture the WebUI's own request (browser DevTools) rather than guessing.
- **API key auth only** (`Authorization: Bearer qbt_…`, qBittorrent ≥ 5.2). No cookie login, no password in `.env`. Keys cannot call `auth/login`/`auth/logout`; `app/webapiVersion` is the auth probe.
- **Sandbox by tag.** The NAS has real torrents. Anything that changes state must go through `TorrentPolicy` and only act on torrents carrying `QBT_SANDBOX_TAG` (default `poc`). `add` always applies that tag. Examples and tests never touch untagged torrents.
- **Paths in API calls are container paths** (`/data/torrents/...`), not NAS paths (`/volume1/data/torrents/...`), because qBittorrent runs in a container.
- **The fake can't prove the wire format.** A new API call needs a real-NAS run (an example script) before it becomes an MCP tool.
- **Order for new operations:** library method + fake + test → real-NAS example → MCP tool → docs (`use-cases.md`, `mcp-server.md`).
- **Nothing in the library or the MCP server may print to stdout**; with the stdio transport, stdout is the protocol channel. Use `logging` to stderr.
- **`mcp` is 2.x:** use `mcp.server.mcpserver.MCPServer` and `mcp_types.ToolAnnotations` (snake_case), as the sibling repo does. Don't follow 1.x `FastMCP` examples.
- **Never commit `.env` or `out/`** (gitignored), and keep them in `.dockerignore`. The repo is public: no real IP, hostname, API key or torrent names in docs or samples.

## Repo workflow

- Public repo `nsierraj/maida-qbittorrent-api-poc`, default branch `main`.
- **Branch protection on `main`:** changes need a PR and green checks `test (py3.11)`, `test (py3.12)`, `test (py3.13)`. Force-push and deletion are blocked. Admins are not enforced, so don't push to `main` directly anyway.
- Work on a branch, open a PR, wait for CI (`gh pr checks --watch`), then squash-merge with `gh pr merge --squash --delete-branch`.
- **CI**: `uv sync --locked` then `uv run pytest`. Pin actions to a full version tag. If `uv.lock` is out of date, CI fails; run `uv lock`.
- **Dependabot** opens weekly PRs for GitHub Actions and `uv` dependencies.

## Releases

- SemVer; the version lives in `pyproject.toml`. Record changes under `[Unreleased]` in `CHANGELOG.md` in the same PR as the change.
- To release: a PR moves `[Unreleased]` to a dated `[X.Y.Z]` section, bumps `pyproject.toml` and runs `uv lock`. After it merges, tag `main` and run `gh release create vX.Y.Z` with that section as the notes. Nothing is published to PyPI.
