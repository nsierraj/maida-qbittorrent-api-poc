# The qBittorrent MCP server

It runs either on your computer, started by Claude Code over stdio, or as a container on the NAS that
clients reach over HTTPS ([Running in Container Manager](#running-in-container-manager)).

`qbittorrent-mcp` lets Claude (or any MCP client) read and, if you allow it, manage your qBittorrent
through the WebUI API. It's built on the `qbittorrent_poc` library, and every tool is a use case
verified on the real server ([use-cases.md](use-cases.md)).

## Setup (stdio, on your computer)

1. Configure `.env` as for the examples (README): `QBT_HOST`, `QBT_PORT`, `QBT_API_KEY`,
   `QBT_SANDBOX_TAG`, `QBT_SANDBOX_SAVEPATH`.
2. Register it with Claude Code, from the repo folder:

   ```bash
   claude mcp add qbittorrent -- uv run --directory "$PWD" qbittorrent-mcp
   ```

   Claude Code starts the server when needed; it reads `.env` from the repo folder. Check it with
   `/mcp` inside Claude Code, or `claude mcp list`. Remove it with `claude mcp remove qbittorrent`.
3. To allow changes, set `QBT_MCP_ALLOW_WRITES=true` (and `QBT_MCP_ALLOW_DELETE=true` for deleting)
   in `.env`, or pass them at registration with `-e QBT_MCP_ALLOW_WRITES=true`. Restart the server
   (`/mcp` → reconnect) after changing them: tools are registered at startup.

Try the inspector without Claude:

```bash
npx @modelcontextprotocol/inspector uv run --directory "$PWD" qbittorrent-mcp
```

## Running in Container Manager

Instead of Claude Code starting the server on your computer, the server can run as a container on the
NAS, and clients connect over HTTPS. The image is built from the repo's [`Dockerfile`](../Dockerfile)
for x86_64 NAS models.

```text
MCP client ──HTTPS :8444──▶ DSM reverse proxy ──HTTP 127.0.0.1:8766──▶ container :8000 /mcp ──HTTP <NAS IP>:8090──▶ gluetun ▶ qBittorrent WebUI API
```

What changes compared with stdio:

- **Every request needs a token.** Anyone who reaches the port could control qBittorrent within the
  server's policy, so the server checks `Authorization: Bearer <QBT_MCP_TOKEN>` on every request and
  refuses to start in HTTP mode without a token of at least 32 characters. `GET /healthz` is the only
  open path, for the container health check. The token is not the qBittorrent API key; that stays in
  `.env` on the NAS.
- **TLS comes from DSM.** The container publishes plain HTTP on `127.0.0.1` only, and DSM's reverse
  proxy serves it over HTTPS with the NAS certificate. Don't forward the port on your router.
- **Ports.** 8766 and 8444 are used so this runs next to the `synology-mcp` container (8765 and 8443).
- **Responses are plain JSON**, not SSE streams, because the reverse proxy buffers streams.
- **URL adds are guarded.** Inside the NAS, `qbt_add_torrent` fetches `.torrent` URLs only from public
  addresses (every resolved address and every redirect is checked), then uploads the file to
  qBittorrent, so neither the server nor qBittorrent can be pointed at DSM or the LAN.

### 1. Prepare the project folder

Copy the repo to `/volume1/docker/qbittorrent-mcp`, so `docker-compose.yml`, `Dockerfile` and `src/` sit
directly in it. Either:

- **Over SSH from your computer** (only committed files, so `.env` and `.venv` stay out):

  ```bash
  git archive --format=tar main | ssh <nas> 'mkdir -p /volume1/docker/qbittorrent-mcp && tar -x -C /volume1/docker/qbittorrent-mcp'
  ```

- **Or in File Station:** `git archive --format=zip -o qbittorrent-mcp.zip main`, create
  `docker/qbittorrent-mcp`, upload the zip, **Extract here**, delete the zip.

### 2. Create `.env`

Start from [`.env.container.example`](../.env.container.example):

| Setting | In the container |
| --- | --- |
| `QBT_HOST` | The NAS's LAN IP. Inside the container, `localhost` is the container itself. |
| `QBT_PORT` | gluetun's published WebUI port (`8090`). |
| `QBT_API_KEY` | The same key as in your local `.env`. |
| `QBT_SANDBOX_TAG`, `QBT_SANDBOX_SAVEPATH`, `QBT_MCP_ALLOW_*` | As for stdio. Start read-only. |
| `QBT_MCP_TOKEN` | `openssl rand -hex 32`. Clients need the same value (step 5). |
| `QBT_MCP_TRANSPORT`, `QBT_MCP_HOST`, `QBT_MCP_PORT` | Leave them out: `docker-compose.yml` sets them. |

Keep it readable by your admin account only (`chmod 600 .env` over SSH). After changing it, recreate the
container (a restart keeps the old values).

**Alternative network.** Instead of the NAS IP, the container can join gluetun's network and use
`QBT_HOST=gluetun`, so traffic never leaves Docker: uncomment the `networks` lines in
`docker-compose.yml`. This server's qBittorrent accepts the `gluetun` host name (errata E3), and gluetun's
firewall must allow input from that network on 8090.

### 3. Create the project

1. Container Manager → **Project** → **Create**: name `qbittorrent-mcp`, path `/volume1/docker/qbittorrent-mcp`,
   use the existing `docker-compose.yml`. Leave **Web Station** unchecked.
2. It builds the image and starts the container. Over SSH, `sudo docker compose up -d --build` in that
   folder does the same.
3. Check it over SSH: `curl http://127.0.0.1:8766/healthz` prints `ok`.

### 4. Add HTTPS with the reverse proxy

Use the same hostname as your other NAS services: a name in the certificate's Subject Alternative Name
that resolves to the NAS's LAN IP on your computers (see the synology-mcp guide for `/etc/hosts` or a
local DNS override).

1. Control Panel → **Login Portal** → **Advanced** → **Reverse Proxy** → **Create**:

   | | Protocol | Hostname | Port |
   | --- | --- | --- | --- |
   | Source | HTTPS | your NAS hostname | 8444 |
   | Destination | HTTP | `127.0.0.1` | 8766 |

2. **Advanced Settings** → proxy read timeout 600 s: adding, moving and deleting wait inside one request.
3. Control Panel → **Security** → **Certificate** → **Settings**: pick the certificate for the new entry.
4. If the DSM firewall is on, allow 8444 from your LAN only.
5. Check from your computer: `curl https://<hostname>:8444/healthz` prints `ok`, and
   `curl -s -o /dev/null -w '%{http_code}' -X POST https://<hostname>:8444/mcp` prints `401`.

### 5. Connect Claude Code

```bash
claude mcp add --transport http qbittorrent-nas https://<hostname>:8444/mcp \
  --header "Authorization: Bearer <QBT_MCP_TOKEN>"
```

Add `--scope user` to use it from every project. The stdio registration (`qbittorrent`) can stay for
development, or be removed with `claude mcp remove qbittorrent`.

**Updating:** copy the new files over (step 1), then rebuild: `sudo docker compose up -d --build`, or
stop the project and build it again in Container Manager.

## Safety model

| Layer | What it does |
| --- | --- |
| Tool registration | Read tools always exist. Change tools exist only with `QBT_MCP_ALLOW_WRITES=true`; `qbt_delete_torrents` only with `QBT_MCP_ALLOW_DELETE=true` as well. A disabled tool isn't hidden behind an error: it doesn't exist. |
| Sandbox (`TorrentPolicy` via `Sandbox`) | Changes only touch torrents tagged `QBT_SANDBOX_TAG` (default `poc`). `all` is refused, a batch with one outsider is refused whole, the sandbox tag can't be removed, and save paths and moves stay inside `QBT_SANDBOX_SAVEPATH`. Refusals happen before any request is sent. |
| Adding | `qbt_add_torrent` identifies the torrent first (hash from the magnet, or by fetching the `.torrent` from a public address only, checking every redirect, then uploading the file rather than passing the URL to qBittorrent), refuses one that already exists, always tags it, sends `autoTMM=false` and `useDownloadPath=false` so the data really goes into the sandbox, checks where the server put it, and removes it if that's outside. Added stopped unless `start=true`. |
| Never exposed | `app/setPreferences`, `app/shutdown`, the full `app/preferences` (it holds the WebUI password hash and other secrets), RSS, search. |
| Output | The API key never appears. Tracker URLs show only `scheme://host` (private trackers embed passkeys), peers are summarized without IPs, and IPs in log lines are masked. `qbt_server_info` does show the external IP: it's how you check the VPN is in front. |
| Annotations | Read tools are `read_only`; change tools are not destructive; `qbt_add_torrent` is open-world (it downloads); `qbt_delete_torrents` is destructive. Clients use these to decide what to ask you about. |

Torrents outside the sandbox can be read but never changed through this server. To manage one,
tag it with the sandbox tag in the WebUI yourself.

## Tools

Torrents are identified by info hash, a hash prefix, or part of the name. An exact hash wins, then an
exact name; anything matching more than one torrent is refused with the candidates listed.

| Tool | Needs | What it does |
| --- | --- | --- |
| `qbt_server_info` | – | Version, connection status, external IP (VPN), DHT nodes, speeds and limits, free disk space, all-time totals, torrents by state, and this server's policy |
| `qbt_list_torrents` | – | List with `filter` (12 5.x filters), `category`, `tag_name`, `name_contains`, `sort`, `reverse`, `limit` (1–200), `offset`; returns `total`, `has_more`, `next_offset` |
| `qbt_torrent_details` | – | One torrent: status, transfer totals, swarm, largest files, trackers (host only), peer summary (clients, countries, connection types) |
| `qbt_list_categories_and_tags` | – | Categories with save path and torrent counts, tags with counts |
| `qbt_whats_changed` | – | First call (`since=0`) is a snapshot; pass the returned `since` to get only torrents added, removed or changed, and changed server totals (`sync/maindata`) |
| `qbt_main_log` | – | Log entries at or above `min_level`, newest last; `after_id` for only newer ones |
| `qbt_add_torrent` | writes | Magnet or `.torrent` URL into the sandbox; `category` (existing), `tags`, `start` |
| `qbt_stop_torrents`, `qbt_start_torrents` | writes | Stop or start; waits until the state changes |
| `qbt_recheck_torrents` | writes | Re-verify data (state shows `checkingDL`/`checkingUP` meanwhile) |
| `qbt_set_category` | writes | Set or clear (`""`) an existing category |
| `qbt_add_tags`, `qbt_remove_tags` | writes | Tags (not the sandbox tag) |
| `qbt_rename_torrent` | writes | Display name only |
| `qbt_move_torrents` | writes | Move data to a folder inside the sandbox path; waits for the move |
| `qbt_delete_torrents` | writes + delete | Remove; `delete_files` is required (true also deletes the data) |

## Prompts

| Prompt | What it asks Claude to do |
| --- | --- |
| `download_status` | VPN and connection check, what's downloading, stalled or errored and why, recent warnings. Changes nothing. |
| `clean_sandbox` | List sandbox torrents and, after you confirm, delete them (or point to `03_lifecycle.py --cleanup` when deleting is disabled). |

Prompts only produce instructions; Claude still calls the tools, so they can't bypass the policy.

## Errors

Tool errors come back as readable messages: `Refused by the sandbox policy (nothing was sent): …`,
`qBittorrent: torrents/… -> HTTP 409: …`, ambiguous or unknown torrent names with candidates,
`qBittorrent rejected the API key. Check QBT_API_KEY …`, or `Cannot reach qBittorrent at … Check
QBT_HOST and QBT_PORT.`

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `/mcp` shows the server failed | Run `uv run qbittorrent-mcp` in the repo folder: a missing `.env` setting is reported on stderr. |
| "rejected the API key" | Regenerate the key in the WebUI (Options → Web UI → API Key) and update `QBT_API_KEY`. Too many failures ban your IP for `web_ui_ban_duration` (default an hour). |
| Change tools missing | `QBT_MCP_ALLOW_WRITES=true` (and `QBT_MCP_ALLOW_DELETE=true`), then reconnect the server. |
| "Refused by the sandbox policy" | Intended: the torrent isn't tagged with the sandbox tag, or the path is outside the sandbox. |
| A change times out | qBittorrent answers before changes are visible; large moves and rechecks take time. Check with `qbt_torrent_details`. |

## Development

- `uv run pytest tests/test_mcp_server.py`: the server through the SDK's in-process client against the fake.
- Nothing in `qbittorrent_mcp` or the library may print to stdout (it's the stdio protocol channel).
- `mcp` is 2.x: `mcp.server.mcpserver.MCPServer`, `mcp_types.ToolAnnotations` (snake_case).

### Adding a tool

1. The library method in `webui.py` (plus `Sandbox` if it changes anything), the fake, and tests.
2. A real-NAS run through an example, with findings in `webui-api.md` §8.
3. The tool in `server.py`: pick the right annotation and tier, shape the output compactly, never return
   secrets. Add it to the tool sets in `tests/test_mcp_server.py` and test it, including a refusal
   that sends nothing.
4. This page and `use-cases.md` (the MCP tool column).
