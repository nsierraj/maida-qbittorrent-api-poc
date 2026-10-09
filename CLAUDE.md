# maida-qbittorrent-api-poc

Python library, examples and (later) an MCP server for the qBittorrent WebUI API (qBittorrent 5.2.x, WebAPI 2.15), verified against the user's real NAS. Sibling of `maida-synology-api-poc`, which this repo mirrors in structure and workflow.

## Commands

- `uv sync`: install (Python 3.11–3.13; `.python-version` pins 3.13 to match CI and the container image)
- `uv run pytest`: the whole suite, against the fake qBittorrent. Must pass before any commit. CI runs it on Python 3.11–3.13.
- `uv run qbittorrent-mcp`: the MCP server (stdio). It reads the same `.env`; `QBT_MCP_ALLOW_WRITES` and `QBT_MCP_ALLOW_DELETE` enable the change and delete tools.
- `uv run examples/0N_*.py`: real-NAS runs. They need `.env` (it's on this Mac and the NAS is reachable), so they can be run from here once the user gives the go-ahead for that stage; say afterwards what changed on the NAS and confirm it's clean. Write examples only touch torrents tagged `QBT_SANDBOX_TAG`.
- `Dockerfile` / `docker-compose.yml`: the HTTP server as a Container Manager project on the NAS (x86_64, ports 127.0.0.1:8766 → DSM reverse proxy 8444). No local Docker here; CI's `docker build` job checks the image. SSH to the NAS works (`ssh synology`, admin), but `docker` needs `sudo` with a password, so starting the container is the user's step.

## Code

- `src/qbittorrent_poc/`: the library. `client.py` (HTTP + API key), `webui.py` (`WebUI`, one method per use case; all wire-format knowledge), `fields.py` (reference field sets per endpoint; "real 5.2.3" sets are authoritative, "wiki"/"source" sets are unverified), `samples.py` (redaction), `policy.py` (`TorrentPolicy`), `sandbox.py` (`Sandbox`: the only way examples and the MCP server change anything), `config.py`, `errors.py`, `fmt.py`.
- `src/qbittorrent_mcp/server.py`: the MCP server: read tools always, change tools behind `QBT_MCP_ALLOW_WRITES`, delete behind `QBT_MCP_ALLOW_DELETE` too, 2 prompts. All changes go through `Sandbox`.
- `examples/`: numbered scripts run by hand against the real NAS.
- `tests/`: `fake_qbt.py` is an in-memory qBittorrent; when you learn a new quirk on the real server, add it to the fake and add a test.
- `docs/qbittorrent/webui-api.md`: condensed API reference with an Errata section. Read it first.

## Rules that aren't obvious from the code

- **All changes go through a pull request**, never a direct push to `main`. CI (`.github/workflows/ci.yml`) must be green. Workflows must not use secrets, `.env` or a real NAS.
- **The wiki lags the server.** The official wiki page is for 5.0 and still says `paused` in places; qBittorrent 5.x uses `torrents/stop`, `torrents/start`, the `stopped` filter and `stoppedDL`/`stoppedUP` states. When the wiki and the real server disagree, trust `docs/qbittorrent/webui-api.md` §Errata, and record what the server did. If an operation fails, capture the WebUI's own request (browser DevTools) rather than guessing.
- **API key auth only** (`Authorization: Bearer qbt_…`, qBittorrent ≥ 5.2). No cookie login, no password in `.env`. Keys cannot call `auth/login`/`auth/logout`; `app/webapiVersion` is the auth probe.
- **Sandbox by tag.** The NAS has real torrents. Anything that changes state goes through `Sandbox`, which applies `TorrentPolicy` before sending anything: only torrents tagged `QBT_SANDBOX_TAG` (default `poc`), never `all`, the sandbox tag can't be removed, paths stay inside `QBT_SANDBOX_SAVEPATH`, and writes and deletes are separate opt-ins. `add` always applies the tag. Raw `WebUI` write methods exist for tests; don't call them from examples or the MCP server. Tests assert that refused calls send no request.
- **Paths in API calls are container paths** (`/data/torrents/...`), not NAS paths (`/volume1/data/torrents/...`), because qBittorrent runs in a container.
- **URL fetches must stay public.** `torrentfile.fetch()` refuses non-public addresses (every resolved address and every redirect hop) and the bytes are uploaded to qBittorrent, never the URL. Inside the NAS anything else would let a tool reach DSM or the LAN. Tests stub DNS (`dns` fixture); never make real lookups in tests.
- **The fake can't prove the wire format.** A new API call needs a real-NAS run (an example script) before it becomes an MCP tool.
- **Order for new operations:** library method + fake + test → real-NAS example → MCP tool → docs (`use-cases.md`, `mcp-server.md`).
- **Nothing in the library or the MCP server may print to stdout**; with the stdio transport, stdout is the protocol channel. Use `logging` to stderr.
- **`mcp` is 2.x:** use `mcp.server.mcpserver.MCPServer` and `mcp_types.ToolAnnotations` (snake_case), as the sibling repo does. Don't follow 1.x `FastMCP` examples.
- **Example output gets pasted into chats.** Anything an example prints or saves goes through `samples.py`: no tracker paths (passkeys), peer or external IPs, raw log messages, and in samples no names, hashes or paths. Add a test that the secret doesn't appear when you add output.
- **After a real-NAS run**, record differences in `webui-api.md` §8, update the `fields.py` set (mark it "real 5.2.3") and the fake, in one PR.
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
