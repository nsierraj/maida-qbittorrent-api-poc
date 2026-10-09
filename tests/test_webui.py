import pytest

from qbittorrent_poc import FILTERS
from qbittorrent_poc.webui import join_hashes, split_tags


def test_versions_and_build(api):
    assert api.app_version() == "v5.2.3"
    assert api.webapi_version() == "2.15.1"
    assert api.build_info()["libtorrent"].startswith("2.")
    assert api.default_save_path() == "/data/torrents/completed"


def test_security_settings_never_include_secrets(api, qbt):
    settings = api.webui_security_settings()
    assert settings["web_ui_max_auth_fail_count"] == 5
    assert settings["web_ui_host_header_validation_enabled"] is False
    assert "web_ui_password" not in settings and "proxy_password" not in settings
    assert all(v not in str(settings) for v in ("fake-password-hash", "fake-proxy-secret"))


def test_torrent_rows_have_the_real_field_set(api):
    from qbittorrent_poc import TORRENT_FIELDS

    row = api.list_torrents()[0]
    assert set(row) == set(TORRENT_FIELDS)
    assert "private" in row and "isPrivate" not in row


def test_transfer_info(api, qbt):
    info = api.transfer_info()
    assert info["connection_status"] == "connected"
    assert info["dl_info_speed"] == sum(t["dlspeed"] for t in qbt.torrents)
    assert api.alt_speed_limits_enabled() is False
    qbt.alt_speed = True
    assert api.alt_speed_limits_enabled() is True


def test_list_all(api, qbt):
    assert len(api.list_torrents()) == len(qbt.torrents)


@pytest.mark.parametrize(("flt", "expected"), [
    ("downloading", {"downloading", "stoppedDL"}),
    ("seeding", {"uploading", "stalledUP"}),
    ("stopped", {"stoppedDL", "stoppedUP"}),
    ("running", {"downloading", "uploading", "stalledUP"}),
    ("completed", {"uploading", "stoppedUP", "stalledUP"}),
    ("stalled_uploading", {"stalledUP"}),
    ("errored", set()),
])
def test_filters_use_5x_states(api, flt, expected):
    assert {t["state"] for t in api.list_torrents(flt)} == expected


def test_unknown_filter_is_refused_locally(api, qbt):
    with pytest.raises(ValueError, match="stopped"):
        api.list_torrents("paused")  # 4.x name
    assert qbt.requests == []


def test_every_filter_is_accepted(api):
    for flt in FILTERS:
        api.list_torrents(flt)


def test_category_and_tag(api):
    assert {t["category"] for t in api.list_torrents(category="linux")} == {"linux"}
    assert all(t["category"] == "" for t in api.list_torrents(category=""))
    assert len(api.list_torrents(tag="keep")) == 2
    assert all(t["tags"] == "" for t in api.list_torrents(tag=""))


def test_sort_limit_offset(api):
    names = [t["name"] for t in api.list_torrents(sort="size", reverse=True)]
    assert names[0].startswith("ubuntu")
    page = api.list_torrents(sort="name", limit=2, offset=1)
    assert [t["name"] for t in page] == sorted(t["name"] for t in api.list_torrents())[1:3]
    assert len(api.list_torrents(sort="name", offset=-1)) == 1


def test_hashes_filter(api, qbt):
    wanted = [qbt.torrents[0]["hash"], qbt.torrents[2]["hash"]]
    assert {t["hash"] for t in api.list_torrents(hashes=wanted)} == set(wanted)
    assert qbt.requests[-1][2]["hashes"] == "|".join(wanted)


def test_categories_and_tags(api):
    cats = api.categories()
    assert cats["linux"]["savePath"] == "/data/torrents/linux"
    assert cats["video"]["savePath"] == ""  # empty = default save path
    assert cats["video"]["share_limit_action"] == "Default"
    assert set(api.tags()) == {"keep", "seed"}


def test_helpers():
    assert join_hashes(["a", "b"]) == "a|b"
    assert join_hashes("all") == "all"
    assert join_hashes(None) is None
    assert split_tags("keep, seed,") == ["keep", "seed"]
    assert split_tags("") == []
