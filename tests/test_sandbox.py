import pytest

from qbittorrent_poc import PolicyError, Sandbox, TorrentPolicy

from .test_webui_write import H, MAGNET


@pytest.fixture
def box(api):
    return Sandbox(api, TorrentPolicy("poc", "/data/torrents/poc", allow_writes=True, allow_delete=True))


def writes_sent(qbt):
    return [e for m, e, _ in qbt.requests if m == "POST"]


def test_add_always_tags_and_stays_in_the_sandbox(box, api, qbt):
    box.add([MAGNET], tags=["extra"])
    data = qbt.requests[-1][2]
    assert (data["autoTMM"], data["useDownloadPath"]) == ("false", "false")
    row = api.list_torrents(hashes=[H])[0]
    assert row["tags"] == "extra, poc" and row["save_path"] == "/data/torrents/poc"
    assert box.policy.check_row(row) is row
    with pytest.raises(PolicyError):
        box.add([MAGNET], savepath="/data/torrents/completed")


def test_untagged_torrents_are_refused_without_a_request(box, qbt):
    outsider = qbt.torrents[0]["hash"]
    before = list(writes_sent(qbt))
    for call in (lambda: box.stop([outsider]), lambda: box.start(outsider), lambda: box.recheck([outsider]),
                 lambda: box.rename(outsider, "x"), lambda: box.add_tags([outsider], ["poc"]),
                 lambda: box.set_category([outsider], "linux"),
                 lambda: box.set_location([outsider], "/data/torrents/poc"),
                 lambda: box.delete([outsider], delete_files=True), lambda: box.stop("all")):
        with pytest.raises(PolicyError):
            call()
    assert writes_sent(qbt) == before
    assert qbt.torrents[0]["state"] == "downloading"


def test_mixed_batch_is_refused_whole(box, qbt):
    box.add([MAGNET])
    with pytest.raises(PolicyError):
        box.stop([H, qbt.torrents[0]["hash"]])
    assert "torrents/stop" not in writes_sent(qbt)


def test_capability_flags(api, qbt):
    ro = Sandbox(api, TorrentPolicy("poc", "/data/torrents/poc"))
    with pytest.raises(PolicyError, match="ALLOW_WRITES"):
        ro.add([MAGNET])
    no_delete = Sandbox(api, TorrentPolicy("poc", "/data/torrents/poc", allow_writes=True))
    no_delete.add([MAGNET])
    with pytest.raises(PolicyError, match="ALLOW_DELETE"):
        no_delete.delete([H], delete_files=False)


def test_sandbox_ops(box, api, qbt):
    box.add([MAGNET])
    box.start([H])
    box.stop(H)
    assert box.ensure_category("poc", "/data/torrents/poc") is True
    assert box.ensure_category("poc") is False
    box.set_category([H], "poc")
    box.add_tags([H], ["poc-extra"])
    box.remove_tags([H], ["poc-extra"])
    with pytest.raises(PolicyError):
        box.remove_tags([H], ["poc"])
    box.rename(H, "renamed")
    box.set_location([H], "/data/torrents/poc/moved")
    with pytest.raises(PolicyError):
        box.set_location([H], "/data/torrents")
    row = api.list_torrents(hashes=[H])[0]
    assert (row["category"], row["name"], row["save_path"], row["tags"]) == (
        "poc", "renamed", "/data/torrents/poc/moved", "poc")


def test_wait_for_times_out(box, monkeypatch):
    import time

    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError):
        box.wait_for(H, lambda r: r is not None, timeout=15)


def test_cleanup(box, api, qbt):
    box.add([MAGNET])
    box.ensure_category("poc", "/data/torrents/poc")
    box.set_category([H], "poc")
    box.add_tags([H], ["poc-extra"])
    others = len(qbt.torrents) - 1
    removed = box.cleanup(extra_tags=["poc-extra", "poc"], categories=["poc", "linux"])
    assert removed == {"torrents": [H], "tags": ["poc-extra"], "categories": ["poc"]}
    assert len(qbt.torrents) == others and qbt.deleted_files == [H]
    assert "linux" in api.categories()  # still used by other torrents
