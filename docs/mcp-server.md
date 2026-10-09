# The qBittorrent MCP server

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

## Safety model

| Layer | What it does |
| --- | --- |
| Tool registration | Read tools always exist. Change tools exist only with `QBT_MCP_ALLOW_WRITES=true`; `qbt_delete_torrents` only with `QBT_MCP_ALLOW_DELETE=true` as well. A disabled tool isn't hidden behind an error: it doesn't exist. |
| Sandbox (`TorrentPolicy` via `Sandbox`) | Changes only touch torrents tagged `QBT_SANDBOX_TAG` (default `poc`). `all` is refused, a batch with one outsider is refused whole, the sandbox tag can't be removed, and save paths and moves stay inside `QBT_SANDBOX_SAVEPATH`. Refusals happen before any request is sent. |
| Adding | `qbt_add_torrent` identifies the torrent first (hash from the magnet, or by fetching the `.torrent`), refuses one that already exists, always tags it, sends `autoTMM=false` and `useDownloadPath=false` so the data really goes into the sandbox, checks where the server put it, and removes it if that's outside. Added stopped unless `start=true`. |
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
