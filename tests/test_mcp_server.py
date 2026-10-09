"""The MCP server, driven through the SDK's in-process client against the fake qBittorrent."""

import json

import pytest
from mcp import Client

from qbittorrent_mcp.server import QbtSession, ServerConfig, build_server, client_factory
from qbittorrent_poc import QbtClient, Settings, TorrentPolicy

from .fake_qbt import API_KEY, ARCH_HASH, ARCH_URL, HOST, PORT

READ_TOOLS = {"qbt_server_info", "qbt_list_torrents", "qbt_torrent_details", "qbt_list_categories_and_tags",
              "qbt_whats_changed", "qbt_main_log"}
WRITE_TOOLS = {"qbt_add_torrent", "qbt_stop_torrents", "qbt_start_torrents", "qbt_recheck_torrents",
               "qbt_set_category", "qbt_add_tags", "qbt_remove_tags", "qbt_rename_torrent", "qbt_move_torrents"}
DELETE_TOOLS = {"qbt_delete_torrents"}
LUBUNTU = "magnet:?xt=urn:btih:e3fbc63821098e11d5be6230b737765980ac354d&dn=lubuntu-26.04-desktop-amd64.iso"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_server(writes=False, delete=False):
    policy = TorrentPolicy("poc", "/data/torrents/poc", allow_writes=writes, allow_delete=delete)
    return build_server(ServerConfig(settings=None, policy=policy),
                        QbtSession(lambda: QbtClient(HOST, PORT, api_key=API_KEY)))


async def call(server, tool_name, /, **args):
    async with Client(server) as c:
        return await c.call_tool(tool_name, args)


def payload(result):
    assert not result.is_error, result.content
    text = result.content[0].text if result.content else ""
    assert API_KEY not in text
    if result.structured_content is not None:
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data
    return json.loads(text)


def error_text(result):
    assert result.is_error
    return result.content[0].text


def posts(qbt):
    return [e for m, e, _ in qbt.requests if m == "POST"]


@pytest.mark.anyio
@pytest.mark.parametrize("writes,delete,expected", [
    (False, False, READ_TOOLS),
    (False, True, READ_TOOLS),  # delete alone grants nothing
    (True, False, READ_TOOLS | WRITE_TOOLS),
    (True, True, READ_TOOLS | WRITE_TOOLS | DELETE_TOOLS),
])
async def test_tools_registered_per_policy(qbt, writes, delete, expected):
    async with Client(make_server(writes, delete)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        prompts = {p.name for p in (await c.list_prompts()).prompts}
    assert set(tools) == expected
    assert all(tools[n].annotations.read_only_hint for n in READ_TOOLS)
    if writes:
        assert tools["qbt_add_torrent"].annotations.open_world_hint is True
        assert not tools["qbt_stop_torrents"].annotations.destructive_hint
    if writes and delete:
        assert tools["qbt_delete_torrents"].annotations.destructive_hint is True
    assert prompts == {"download_status", "clean_sandbox"}


@pytest.mark.anyio
async def test_server_info(qbt):
    info = payload(await call(make_server(), "qbt_server_info"))
    assert info["qbittorrent_version"] == "v5.2.3" and info["connection_status"] == "connected"
    assert info["external_ip_v4"] == "203.0.113.7"
    assert info["torrents_total"] == 5 and info["torrents_by_state"]["downloading"] == 1
    assert info["server_policy"] == {"changes_enabled": False, "delete_enabled": False,
                                     "sandbox_tag": "poc", "sandbox_path": "/data/torrents/poc"}
    assert info["free_disk_space"].endswith("TiB")


@pytest.mark.anyio
async def test_list_torrents_filters_and_pages(qbt):
    server = make_server()
    first = payload(await call(server, "qbt_list_torrents", limit=2))
    assert (first["total"], first["count"], first["has_more"], first["next_offset"]) == (5, 2, True, 2)
    assert first["torrents"][0]["name"] == "big-buck-bunny-1080p.mkv"  # newest first
    last = payload(await call(server, "qbt_list_torrents", limit=2, offset=4))
    assert last["has_more"] is False and last["next_offset"] is None
    stopped = payload(await call(server, "qbt_list_torrents", filter="stopped"))
    assert {t["state"] for t in stopped["torrents"]} == {"stoppedDL", "stoppedUP"}
    named = payload(await call(server, "qbt_list_torrents", name_contains="ARCH"))
    assert [t["name"] for t in named["torrents"]] == ["archlinux-2026.10.01-x86_64.iso"]
    assert named["torrents"][0]["tags"] == ["keep", "seed"] and named["torrents"][0]["in_sandbox"] is False
    assert "stopped" in error_text(await call(server, "qbt_list_torrents", filter="paused"))
    assert "sort" in error_text(await call(server, "qbt_list_torrents", sort="nope"))


@pytest.mark.anyio
async def test_torrent_details_hide_ips_and_passkeys(qbt):
    details = payload(await call(make_server(), "qbt_torrent_details", torrent="ubuntu"))
    assert details["name"] == "ubuntu-26.04-desktop-amd64.iso"
    assert details["connected_peers"]["connected"] == 2
    assert {t["tracker"] for t in details["trackers"]} >= {"https://tracker.example.org", "** [DHT] **"}
    text = json.dumps(details)
    assert "198.51.100." not in text and "/announce" not in text and "peers.example.net" not in text
    assert details["files_total"] == 1


@pytest.mark.anyio
async def test_ambiguous_and_unknown_identifiers(qbt):
    server = make_server()
    assert "torrents match 'iso'" in error_text(await call(server, "qbt_torrent_details", torrent="iso"))
    assert "No torrent matches" in error_text(await call(server, "qbt_torrent_details", torrent="nothing"))


@pytest.mark.anyio
async def test_categories_and_tags(qbt):
    data = payload(await call(make_server(), "qbt_list_categories_and_tags"))
    assert {"name": "video", "save_path": "(default save path)", "torrents": 1} in data["categories"]
    assert {"name": "keep", "torrents": 2} in data["tags"] and data["uncategorized_torrents"] == 1


@pytest.mark.anyio
async def test_whats_changed(qbt):
    server = make_server()
    snap = payload(await call(server, "qbt_whats_changed"))
    assert snap["full_snapshot"] is True and snap["torrents_total"] == 5
    qbt.torrents[0]["progress"] = 0.9
    gone = qbt.torrents.pop(1)
    delta = payload(await call(server, "qbt_whats_changed", since=snap["since"]))
    assert delta["full_snapshot"] is False
    assert delta["changed"] == [{"hash": qbt.torrents[0]["hash"], "name": qbt.torrents[0]["name"],
                                 "changes": {"progress": 0.9}}]
    assert delta["removed"] == [gone["hash"]] and delta["added"] == []


@pytest.mark.anyio
async def test_main_log_levels_and_masking(qbt):
    qbt.add_log("Detected external IP. IP: 203.0.113.7", 4)
    log = payload(await call(make_server(), "qbt_main_log"))
    assert [e["level"] for e in log["entries"]] == ["warning", "critical", "warning"]
    assert "203.0.113.7" not in json.dumps(log) and log["last_id"] == 5
    newer = payload(await call(make_server(), "qbt_main_log", min_level="normal", after_id=log["last_id"]))
    assert newer["entries"] == [] and newer["last_id"] == 5


@pytest.mark.anyio
async def test_unreachable_or_rejected_key_explains(qbt):
    bad = build_server(ServerConfig(None, TorrentPolicy()),
                       QbtSession(client_factory(Settings(HOST, PORT, "qbt_wrong"))))
    assert "QBT_API_KEY" in error_text(await call(bad, "qbt_server_info"))


# == changes ======================================================================================
@pytest.mark.anyio
async def test_add_by_url_lands_in_the_sandbox(qbt):
    server = make_server(writes=True)
    added = payload(await call(server, "qbt_add_torrent", source=ARCH_URL))
    assert added["hash"] == ARCH_HASH and added["state"] == "stoppedDL" and added["started"] is False
    assert added["tags"] == ["poc"] and added["save_path"] == "/data/torrents/poc" and added["in_sandbox"]
    row = qbt.torrent(ARCH_HASH)
    assert row["download_path"] == "" and not row["auto_tmm"]
    assert "already in qBittorrent, in the sandbox" in error_text(await call(server, "qbt_add_torrent", source=ARCH_URL))


@pytest.mark.anyio
async def test_add_refusals(qbt):
    server = make_server(writes=True)
    outsider = qbt.torrents[0]["magnet_uri"]
    assert "outside the sandbox" in error_text(await call(server, "qbt_add_torrent", source=outsider))
    assert "Unknown category" in error_text(await call(server, "qbt_add_torrent", source=LUBUNTU, category="nope"))
    assert "magnet link or an http" in error_text(await call(server, "qbt_add_torrent", source="/etc/passwd"))
    assert "torrents/add" not in posts(qbt)


@pytest.mark.anyio
async def test_add_by_url_uploads_the_file_and_refuses_internal_urls(qbt, dns):
    server = make_server(writes=True)
    payload(await call(server, "qbt_add_torrent", source=ARCH_URL))
    add = [d for _, e, d in qbt.requests if e == "torrents/add"][-1]
    assert "urls" not in add and len(add["_files"]) == 1  # bytes, never the URL
    dns["nas.lan"] = ["192.168.1.50"]
    refused = await call(server, "qbt_add_torrent", source="http://nas.lan:5000/webapi/entry.cgi")
    assert "private or internal" in error_text(refused)
    assert "http://nas.lan:5000/webapi/entry.cgi" not in qbt.downloads


@pytest.mark.anyio
async def test_add_started_and_with_category(qbt):
    added = payload(await call(make_server(writes=True), "qbt_add_torrent", source=LUBUNTU,
                               category="linux", tags=["extra"], start=True))
    assert added["state"] == "metaDL" and added["category"] == "linux" and added["tags"] == ["extra", "poc"]


@pytest.mark.anyio
async def test_add_that_lands_outside_is_removed(qbt):
    original = qbt._add
    qbt.routes["torrents/add"] = ("POST", lambda p: original({k: v for k, v in p.items() if k != "useDownloadPath"}))
    result = await call(make_server(writes=True), "qbt_add_torrent", source=ARCH_URL)
    assert "Incomplete data goes to '/data/torrents/incoming'" in error_text(result)
    assert qbt.torrent(ARCH_HASH) is None


@pytest.mark.anyio
async def test_changes_on_sandbox_torrents(qbt):
    server = make_server(writes=True)
    payload(await call(server, "qbt_add_torrent", source=ARCH_URL))
    # The fake also has an unrelated "archlinux-…" torrent outside the sandbox: the name is ambiguous.
    assert "2 torrents match" in error_text(await call(server, "qbt_start_torrents", torrents=["archlinux"]))
    started = payload(await call(server, "qbt_start_torrents", torrents=[ARCH_HASH[:8]]))
    assert started[0]["state"] == "downloading"
    assert payload(await call(server, "qbt_stop_torrents", torrents=[ARCH_HASH[:10]]))[0]["state"] == "stoppedDL"
    assert payload(await call(server, "qbt_recheck_torrents", torrents=[ARCH_HASH]))[0]["state"] == "checkingDL"
    assert payload(await call(server, "qbt_set_category", torrents=[ARCH_HASH], category="linux"))[0]["category"] == "linux"
    assert payload(await call(server, "qbt_add_tags", torrents=[ARCH_HASH], tags=["x"]))[0]["tags"] == ["poc", "x"]
    assert payload(await call(server, "qbt_remove_tags", torrents=[ARCH_HASH], tags=["x"]))[0]["tags"] == ["poc"]
    assert payload(await call(server, "qbt_rename_torrent", torrent=ARCH_HASH, new_name="arch"))["name"] == "arch"
    moved = payload(await call(server, "qbt_move_torrents", torrents=["arch"], location="/data/torrents/poc/m"))
    assert moved[0]["save_path"] == "/data/torrents/poc/m"


@pytest.mark.anyio
async def test_policy_refusals_send_nothing(qbt):
    server = make_server(writes=True, delete=True)
    payload(await call(server, "qbt_add_torrent", source=ARCH_URL))
    before = list(posts(qbt))
    outsider = qbt.torrents[0]["hash"]
    for name, args in [
        ("qbt_stop_torrents", {"torrents": [outsider]}),
        ("qbt_stop_torrents", {"torrents": [ARCH_HASH, outsider]}),
        ("qbt_rename_torrent", {"torrent": outsider, "new_name": "x"}),
        ("qbt_add_tags", {"torrents": [outsider], "tags": ["poc"]}),
        ("qbt_remove_tags", {"torrents": [ARCH_HASH], "tags": ["poc"]}),
        ("qbt_move_torrents", {"torrents": [ARCH_HASH], "location": "/data/torrents/completed"}),
        ("qbt_delete_torrents", {"torrents": [outsider], "delete_files": True}),
    ]:
        assert "Refused by the sandbox policy" in error_text(await call(server, name, **args)), name
    assert posts(qbt) == before
    assert qbt.torrents[0]["state"] == "downloading"


@pytest.mark.anyio
async def test_delete(qbt):
    server = make_server(writes=True, delete=True)
    payload(await call(server, "qbt_add_torrent", source=ARCH_URL))
    result = payload(await call(server, "qbt_delete_torrents", torrents=[ARCH_HASH], delete_files=True))
    assert result == {"deleted": [{"hash": ARCH_HASH, "name": "archlinux-2026.10.01-x86_64.iso"}],
                      "files_deleted": True}
    assert qbt.torrent(ARCH_HASH) is None and qbt.deleted_files == [ARCH_HASH]


@pytest.mark.anyio
async def test_prompts_follow_the_policy(qbt):
    async with Client(make_server()) as c:
        ro = (await c.get_prompt("clean_sandbox", {})).messages[0].content.text
    async with Client(make_server(writes=True, delete=True)) as c:
        rw = (await c.get_prompt("clean_sandbox", {})).messages[0].content.text
        status = (await c.get_prompt("download_status", {})).messages[0].content.text
    assert "--cleanup" in ro and "qbt_delete_torrents" in rw
    assert "qbt_server_info" in status and "Don't change anything" in status
