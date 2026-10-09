"""Stage 3: raw write calls against the fake (no policy)."""

import pytest

from qbittorrent_poc import QbtError
from qbittorrent_poc.webui import magnet_hash

MAGNET = "magnet:?xt=urn:btih:e3fbc63821098e11d5be6230b737765980ac354d&dn=lubuntu-26.04-desktop-amd64.iso"
H = "e3fbc63821098e11d5be6230b737765980ac354d"


def test_magnet_hash_forms():
    assert magnet_hash(MAGNET) == H
    assert magnet_hash("magnet:?xt=urn:btih:4P54MOBBBGHBDVN6MIYLON3WLGAKYNKN") == H
    with pytest.raises(ValueError):
        magnet_hash("https://example.org/file.torrent")


def test_add_stopped_sends_both_names_and_multipart(api, qbt):
    assert api.add([MAGNET], savepath="/data/torrents/poc", tags=["poc"]) == "Ok."
    _, endpoint, data = qbt.requests[-1]
    assert endpoint == "torrents/add"
    assert data["stopped"] == "true" and data["paused"] == "true"
    row = api.list_torrents(hashes=[H])[0]
    assert row["state"] == "stoppedDL" and row["tags"] == "poc" and not row["has_metadata"]


def test_add_twice_fails(api):
    api.add([MAGNET])
    with pytest.raises(QbtError) as exc:
        api.add([MAGNET])
    assert exc.value.status == 409 and "already" in str(exc.value)


def test_add_needs_urls(api):
    with pytest.raises(ValueError):
        api.add([])


def test_stop_start_and_metadata(api, qbt):
    api.add([MAGNET])
    api.start([H])
    assert api.list_torrents(hashes=[H])[0]["state"] == "metaDL"
    qbt.fetch_metadata(H)
    assert api.list_torrents(hashes=[H])[0]["state"] == "downloading"
    api.stop([H])
    assert api.list_torrents(hashes=[H])[0]["state"] == "stoppedDL"
    api.recheck([H])
    assert qbt.rechecked == [H]


def test_post_only_endpoints_refuse_get(client):
    with pytest.raises(QbtError) as exc:
        client.get("torrents/stop", hashes=H)
    assert exc.value.status == 405


def test_categories(api):
    api.create_category("poc", "/data/torrents/poc")
    with pytest.raises(QbtError) as exc:
        api.create_category("poc")
    assert exc.value.status == 409
    api.add([MAGNET])
    api.set_category([H], "poc")
    assert api.list_torrents(hashes=[H])[0]["category"] == "poc"
    with pytest.raises(QbtError) as exc:
        api.set_category([H], "nope")
    assert exc.value.status == 409
    api.remove_categories(["poc"])
    assert "poc" not in api.categories()
    assert api.list_torrents(hashes=[H])[0]["category"] == ""


def test_tags(api):
    api.add([MAGNET], tags=["poc"])
    api.add_tags([H], ["extra", "more"])
    assert api.list_torrents(hashes=[H])[0]["tags"] == "extra, more, poc"
    api.remove_tags([H], ["more"])
    assert api.list_torrents(hashes=[H])[0]["tags"] == "extra, poc"
    with pytest.raises(ValueError):
        api.remove_tags([H], [])  # would remove every tag
    api.delete_tags(["extra"])
    assert "extra" not in api.tags() and api.list_torrents(hashes=[H])[0]["tags"] == "poc"


def test_rename_and_location(api):
    api.add([MAGNET])
    api.rename(H, "renamed")
    assert api.list_torrents(hashes=[H])[0]["name"] == "renamed"
    with pytest.raises(QbtError) as exc:
        api.rename(H, " ")
    assert exc.value.status == 409
    with pytest.raises(QbtError) as exc:
        api.rename("0" * 40, "x")
    assert exc.value.status == 404
    api.set_location([H], "/data/torrents/poc/moved")
    assert api.list_torrents(hashes=[H])[0]["save_path"] == "/data/torrents/poc/moved"
    with pytest.raises(QbtError) as exc:
        api.set_location([H], "")
    assert exc.value.status == 400


def test_delete(api, qbt):
    api.add([MAGNET])
    api.delete(["0" * 40], delete_files=True)  # unknown hash: still 200
    api.delete([H], delete_files=True)
    assert api.list_torrents(hashes=[H]) == [] and qbt.deleted_files == [H]
    deletes = [d for _, e, d in qbt.requests if e == "torrents/delete"]
    assert [d["deleteFiles"] for d in deletes] == ["true", "true"]
