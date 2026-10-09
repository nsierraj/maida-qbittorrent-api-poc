"""Stage 2: per-torrent detail, sync and log."""

import pytest

from qbittorrent_poc import QbtError, fields


def h(qbt, i):
    return qbt.torrents[i]["hash"]


def test_find_by_name_and_prefix(api, qbt):
    assert [t["name"] for t in api.find_torrents("UBUNTU")] == ["ubuntu-26.04-desktop-amd64.iso"]
    assert api.resolve_hash(h(qbt, 2)[:6]) == h(qbt, 2)
    assert api.resolve_hash(h(qbt, 3)) == h(qbt, 3)


def test_resolve_refuses_ambiguous_and_missing(api):
    with pytest.raises(ValueError, match="torrents match 'iso'"):
        api.resolve_hash("iso")
    with pytest.raises(ValueError, match="No torrent matches"):
        api.resolve_hash("nothing-like-this")
    with pytest.raises(ValueError):
        api.resolve_hash("  ")


def test_properties(api, qbt):
    props = api.properties(h(qbt, 0))
    assert props["total_size"] == qbt.torrents[0]["size"]
    assert set(props) == set(fields.PROPERTIES_FIELDS)


def test_unknown_hash_is_404(api):
    with pytest.raises(QbtError) as exc:
        api.properties("0" * 40)
    assert exc.value.status == 404 and "unknown torrent hash" in str(exc.value)


def test_files_and_indexes(api, qbt):
    multi = api.files(h(qbt, 4))
    assert len(multi) == 3 and [f["index"] for f in multi] == [0, 1, 2]
    assert {f["priority"] for f in multi} == {0, 1}
    assert [f["index"] for f in api.files(h(qbt, 4), indexes=[0, 2])] == [0, 2]
    assert qbt.requests[-1][2]["indexes"] == "0|2"
    assert set(multi[0]) == set(fields.FILE_FIELDS)


def test_trackers_include_pseudo_rows(api, qbt):
    rows = api.trackers(h(qbt, 0))
    assert [r["url"] for r in rows if r["tier"] < 0] == ["** [DHT] **", "** [PeX] **", "** [LSD] **"]
    assert {fields.TRACKER_STATUSES[r["status"]] for r in rows} >= {"working", "not working"}


def test_peers_full_then_delta(api, qbt):
    first = api.peers(h(qbt, 0))
    assert first["full_update"] is True and len(first["peers"]) == 2
    qbt.torrents[0]["dlspeed"] = 1
    delta = api.peers(h(qbt, 0), rid=first["rid"])
    assert "full_update" not in delta
    changed = [p for p in delta["peers"].values() if p]
    assert changed == [{"dl_speed": 1}]


def test_stopped_torrent_has_no_peers(api, qbt):
    assert api.peers(h(qbt, 1))["peers"] == {}


def test_maindata_full_then_delta(api, qbt):
    full = api.maindata()
    assert full["full_update"] is True
    assert set(full) >= {"rid", "torrents", "categories", "tags", "server_state"}
    assert len(full["torrents"]) == len(qbt.torrents)
    assert set(full["server_state"]) == set(fields.SERVER_STATE_FIELDS)

    nothing = api.maindata(full["rid"])
    assert set(nothing) == {"rid"} and nothing["rid"] > full["rid"]

    qbt.torrents[0]["progress"] = 0.5
    qbt.free_space -= 1
    removed = qbt.torrents.pop(1)  # stopped, so the peer count stays the same
    qbt.tags.append("new")
    delta = api.maindata(nothing["rid"])
    assert delta["torrents"] == {h(qbt, 0): {"progress": 0.5}}
    assert delta["torrents_removed"] == [removed["hash"]]
    assert delta["tags"] == ["new"]
    assert delta["server_state"] == {"free_space_on_disk": qbt.free_space}


def test_unknown_rid_gets_full_update(api):
    assert api.maindata(999)["full_update"] is True


def test_main_log_levels_and_last_known_id(api, qbt):
    log = api.main_log()
    assert [e["id"] for e in log] == list(range(len(qbt.log)))
    assert {e["type"] for e in api.main_log(normal=False, info=False)} == {4, 8}
    assert api.main_log(last_known_id=log[-1]["id"]) == []
    qbt.add_log("Added new torrent")
    assert [e["message"] for e in api.main_log(last_known_id=log[-1]["id"])] == ["Added new torrent"]
    assert qbt.requests[-1][2]["normal"] == "true"


def test_diff_fields():
    assert fields.diff_fields([], ("a",)) == ([], [])
    assert fields.diff_fields({"a": 1, "b": 2}, ("a", "c")) == (["b"], ["c"])
    assert fields.diff_fields([{"a": 1}, {"z": 1}], ("a",)) == (["z"], [])
