import pytest

from qbittorrent_poc import PolicyError, TorrentPolicy


def row(h, tags="", name="x"):
    return {"hash": h, "tags": tags, "name": name}


def test_capabilities_are_opt_in():
    p = TorrentPolicy()
    with pytest.raises(PolicyError, match="QBT_MCP_ALLOW_WRITES"):
        p.require_writes()
    with pytest.raises(PolicyError, match="QBT_MCP_ALLOW_DELETE"):
        p.require_delete()
    TorrentPolicy(allow_writes=True, allow_delete=True).require_delete()


def test_only_tagged_torrents():
    p = TorrentPolicy("poc")
    assert p.check_torrents(["AA"], [row("aa", "keep, poc")]) == ["aa"]
    with pytest.raises(PolicyError, match="Not tagged: bb x"):
        p.check_torrents(["aa", "bb"], [row("aa", "poc"), row("bb", "keep")])
    with pytest.raises(PolicyError, match="Unknown"):
        p.check_torrents(["cc"], [])
    with pytest.raises(PolicyError, match="'all'"):
        p.check_torrents(["all"], [])
    with pytest.raises(PolicyError):
        p.check_torrents([], [])


def test_tag_matching_is_exact():
    with pytest.raises(PolicyError):
        TorrentPolicy("poc").check_torrents(["aa"], [row("aa", "poc-extra, pocket")])


def test_sandbox_tag_cannot_be_removed():
    p = TorrentPolicy("poc")
    assert p.check_tags_removal(["extra", " "]) == ["extra"]
    with pytest.raises(PolicyError, match="can't be removed"):
        p.check_tags_removal(["extra", "poc"])


def test_paths():
    p = TorrentPolicy(sandbox_path="/data/torrents/poc/")
    assert p.check_path("/data/torrents/poc") == "/data/torrents/poc"
    assert p.check_path("/data/torrents/poc/a/../b") == "/data/torrents/poc/b"
    for bad in ("/data/torrents", "/data/torrents/poc/../completed", "/data/torrents/pocket", "relative"):
        with pytest.raises(PolicyError):
            p.check_path(bad)
    with pytest.raises(PolicyError, match="QBT_SANDBOX_SAVEPATH"):
        TorrentPolicy().check_path("/data/torrents/poc")


def test_bad_tag_config():
    with pytest.raises(ValueError):
        TorrentPolicy("")
    with pytest.raises(ValueError):
        TorrentPolicy("a,b")


def test_check_row_covers_the_incomplete_folder():
    p = TorrentPolicy(sandbox_path="/data/torrents/poc")
    ok = {"save_path": "/data/torrents/poc", "download_path": ""}
    assert p.check_row(ok) is ok
    p.check_row({"save_path": "/data/torrents/poc", "download_path": "/data/torrents/poc/incomplete"})
    with pytest.raises(PolicyError, match="Incomplete data goes to '/data/torrents/incoming'"):
        p.check_row({"save_path": "/data/torrents/poc", "download_path": "/data/torrents/incoming"})
    with pytest.raises(PolicyError):
        p.check_row({"save_path": "/data/torrents/completed", "download_path": ""})
