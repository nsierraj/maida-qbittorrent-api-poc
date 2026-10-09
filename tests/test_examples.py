"""Run the example scripts end to end against the fake server (the real NAS runs are manual)."""

import json
import runpy
import sys
from pathlib import Path

import pytest

from qbittorrent_poc import config

from .fake_qbt import API_KEY, ARCH_HASH, ARCH_SIZE, HOST, PORT

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def env(qbt, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)  # never read the real .env
    for key, value in {
        "QBT_HOST": HOST, "QBT_PORT": str(PORT), "QBT_API_KEY": API_KEY,
        "QBT_SANDBOX_TAG": "poc", "QBT_SANDBOX_SAVEPATH": "/data/torrents/poc",
        "QBT_POC_OUT": str(tmp_path / "out"), "QBT_TEST_TORRENT": "",
    }.items():
        monkeypatch.setenv(key, value)
    return qbt


def run(script: str, *args: str, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [script, *args])
    runpy.run_path(str(EXAMPLES / script), run_name="__main__")


def test_00_probe_auth(env, monkeypatch, capsys):
    run("00_probe_auth.py", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert API_KEY not in out
    assert "key accepted" in out
    assert "auth required (expected)" in out
    assert "wrong key refused (expected)" in out
    # As observed on the real server (2026-10-09):
    assert "CSRF check skipped for API keys" in out
    assert "container names accepted" in out
    assert "GET endpoints also accept POST" in out
    assert "| Probe | HTTP | Meaning |" in out


def test_00_probe_auth_strict_server(env, monkeypatch, capsys):
    env.csrf_with_api_key = True
    env.host_header_validation = True
    run("00_probe_auth.py", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "CSRF check applies to API keys" in out
    assert "host header validation rejects" in out


def test_01_discover(env, monkeypatch, capsys, tmp_path):
    run("01_discover.py", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert API_KEY not in out
    assert "qBittorrent : v5.2.3" in out and "WebAPI      : 2.15.1" in out
    assert "5 in total" in out
    assert "stoppedDL" in out and "stoppedUP" in out
    assert "new fields             : none" in out
    assert "sandbox tag 'poc': not created yet" in out
    assert "external IP : 203.0.113.7" in out
    assert "web_ui_max_auth_fail_count" in out
    assert "fake-password-hash" not in out and "fake-proxy-secret" not in out

    samples = tmp_path / "out" / "samples"
    torrents = json.loads((samples / "torrents_info.json").read_text())
    assert len(torrents) == 5
    raw = (samples / "torrents_info.json").read_text()
    for t in env.torrents:  # no real names, hashes or paths leak into the samples
        assert t["name"] not in raw and t["hash"] not in raw and t["save_path"] not in raw
    assert {t["name"] for t in torrents} == {f"torrent-{i:03d}" for i in range(1, 6)}
    transfer = (samples / "transfer_info.json").read_text()
    assert "203.0.113.7" not in transfer and "<redacted>" in transfer


def test_01_discover_empty_out_setting_means_out(env, monkeypatch, capsys, tmp_path):
    # .env.example has `QBT_POC_OUT=`; an empty value once wrote samples/ into the repo root.
    monkeypatch.setenv("QBT_POC_OUT", "")
    monkeypatch.chdir(tmp_path)
    run("01_discover.py", monkeypatch=monkeypatch)
    assert (tmp_path / "out" / "samples" / "torrents_info.json").exists()
    assert not (tmp_path / "samples").exists()


def test_01_discover_reports_new_fields(env, monkeypatch, capsys):
    for t in env.torrents:
        t["brand_new_field"] = 1
        del t["popularity"]
    env.torrents[0]["state"] = "brandNewState"
    run("01_discover.py", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "new fields             : brand_new_field" in out
    assert "fields not sent        : popularity" in out
    assert "unknown states         : brandNewState" in out


def test_02_inspect_default_is_newest(env, monkeypatch, capsys, tmp_path):
    run("02_inspect.py", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    newest = max(env.torrents, key=lambda t: t["added_on"])
    assert f"[1] Torrent: {newest['name']}" in out
    assert "[10] Errors" in out and "as documented: 404" in out


def test_02_inspect_by_name(env, monkeypatch, capsys, tmp_path):
    run("02_inspect.py", "ubuntu", "--wait", "0", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "[1] Torrent: ubuntu-26.04-desktop-amd64.iso" in out
    assert "1 files, 0 skipped" in out
    assert "tier -1  working" in out and "not working" in out
    assert "2 connected" in out and "clients" in out
    assert "full_update True" in out and "free_space_on_disk" in out
    assert "warning 1" in out and "critical 1" in out
    assert "entries after id 4: 0 (last_known_id works as documented)" in out
    # Reference sets match the fake, so nothing new is reported yet.
    assert out.count("new: none") == 8

    # Safe to paste: no tracker paths, peer IPs, external IP or key.
    assert "/announce" not in out and "198.51.100." not in out and "203.0.113.7" not in out
    assert "peers.example.net" not in out
    assert API_KEY not in out
    assert "https://tracker.example.org " in out

    sample_dir = tmp_path / "out" / "samples"
    for name in ("properties.json", "files.json", "trackers.json", "torrent_peers.json",
                 "maindata_full.json", "maindata_delta.json", "log_main.json"):
        text = (sample_dir / name).read_text()
        for t in env.torrents:
            assert t["name"] not in text and t["hash"] not in text
        assert "198.51.100." not in text and "203.0.113.7" not in text and "/announce" not in text
        assert "peers.example.net" not in text


def test_02_inspect_multi_file_and_stopped(env, monkeypatch, capsys):
    run("02_inspect.py", "bunny", "--wait", "0", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "3 files, 1 skipped" in out and "skip" in out
    run("02_inspect.py", "debian", "--wait", "0", monkeypatch=monkeypatch)
    assert "0 connected  (the torrent is stopped)" in capsys.readouterr().out


def test_02_inspect_ambiguous_query_exits(env, monkeypatch):
    import pytest

    with pytest.raises(SystemExit, match="torrents match"):
        run("02_inspect.py", "iso", monkeypatch=monkeypatch)


LUBUNTU = "magnet:?xt=urn:btih:e3fbc63821098e11d5be6230b737765980ac354d&dn=lubuntu-26.04-desktop-amd64.iso"


def test_03_lifecycle(env, monkeypatch, capsys):
    before = {t["hash"]: dict(t) for t in env.torrents}
    run("03_lifecycle.py", "--run-seconds", "0", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "Test torrent: archlinux-2026.10.01-x86_64.iso, 1.5 GiB, 1 web seeds" in out
    assert "server answered: {'added_torrent_ids': [], 'failure_count': 0, 'pending_count': 1" in out
    assert "appeared: checkingResumeData" in out and "settled : stoppedDL" in out
    assert "download path -," in out
    assert "checkingDL" in out and "verified (stoppedDL)" in out
    assert "stop-on-add: honored" in out
    assert "GET torrents/stop -> HTTP 405 (method enforced)" in out
    assert "category created" in out and "unknown category -> HTTP 409" in out
    assert "after add   : 'poc, poc-extra'" in out and "after remove: 'poc'" in out
    assert out.count("refused locally") == 3 and "move outside the sandbox refused locally" in out
    assert "name now 'poc-renamed-test'" in out
    assert "save path now /data/torrents/poc/moved" in out
    assert "removed tags ['poc-extra'], categories ['poc']" in out
    assert "All lifecycle steps passed." in out
    # Nothing outside the sandbox changed, and nothing was left behind.
    assert {t["hash"]: t for t in env.torrents} == before
    assert env.deleted_files == [ARCH_HASH]
    assert "poc" not in env.categories and "poc-extra" not in env.tags
    assert API_KEY not in out


def test_03_lifecycle_keep_then_cleanup(env, monkeypatch, capsys):
    run("03_lifecycle.py", "--keep", "--run-seconds", "0", monkeypatch=monkeypatch)
    assert "--keep: left" in capsys.readouterr().out
    kept = env.torrent(ARCH_HASH)
    assert kept["state"] == "stoppedDL" and kept["save_path"] == "/data/torrents/poc/moved"

    with pytest.raises(SystemExit, match="--cleanup first"):
        run("03_lifecycle.py", monkeypatch=monkeypatch)

    run("03_lifecycle.py", "--cleanup", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "Removed 1 sandbox torrent(s)" in out
    assert env.torrent(ARCH_HASH) is None and "poc" not in env.categories


def test_03_refuses_a_magnet_already_outside_the_sandbox(env, monkeypatch, qbt):
    monkeypatch.setenv("QBT_TEST_TORRENT", env.torrents[0]["magnet_uri"])
    with pytest.raises(SystemExit, match="without the 'poc' tag"):
        run("03_lifecycle.py", monkeypatch=monkeypatch)
    assert not [e for m, e, _ in env.requests if m == "POST"]


def test_03_needs_a_sandbox_path(env, monkeypatch):
    monkeypatch.setenv("QBT_SANDBOX_SAVEPATH", "")
    with pytest.raises(SystemExit, match="QBT_SANDBOX_SAVEPATH"):
        run("03_lifecycle.py", monkeypatch=monkeypatch)


def test_03_ignored_stop_on_add_is_reported_and_corrected(env, monkeypatch, capsys):
    original = env._add

    def add_running(p):
        p = {**p, "stopped": "false", "paused": "false"}
        return original(p)

    env.routes["torrents/add"] = ("POST", add_running)
    run("03_lifecycle.py", "--run-seconds", "0", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "stop-on-add: IGNORED" in out and "All lifecycle steps passed." in out


@pytest.mark.parametrize("dropped", ["autoTMM", "useDownloadPath"])
def test_03_deletes_a_torrent_the_server_put_outside_the_sandbox(env, monkeypatch, capsys, dropped):
    # A server that ignores autoTMM=false (with auto-management on) or useDownloadPath=false
    # (with the incomplete folder on) would put the data outside the sandbox.
    original = env._add
    env.routes["torrents/add"] = ("POST", lambda p: original({k: v for k, v in p.items() if k != dropped}))
    env.preferences["auto_tmm_enabled"] = True
    with pytest.raises(SystemExit):
        run("03_lifecycle.py", "--run-seconds", "0", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "OUTSIDE the sandbox" in out and "Deleting it before anything is downloaded" in out
    assert env.torrent(ARCH_HASH) is None and env.deleted_files == [ARCH_HASH]


def test_03_recheck_that_resumes_is_stopped_again(env, monkeypatch, capsys):
    env.recheck_resumes = True
    run("03_lifecycle.py", "--run-seconds", "0", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "recheck resumed it" in out and "All lifecycle steps passed." in out


def test_03_with_a_magnet(env, monkeypatch, capsys):
    monkeypatch.setenv("QBT_TEST_TORRENT", LUBUNTU)
    run("03_lifecycle.py", "--run-seconds", "0", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "no metadata yet" in out and "All lifecycle steps passed." in out
    assert "Test torrent:" not in out  # nothing to download for a magnet


def test_03_torrent_url_downloads_metadata(env, monkeypatch, capsys):
    run("03_lifecycle.py", "--keep", "--run-seconds", "0", monkeypatch=monkeypatch)
    kept = env.torrent(ARCH_HASH)
    assert kept["has_metadata"] and kept["size"] == ARCH_SIZE


def test_03_unreadable_torrent_url(env, monkeypatch):
    monkeypatch.setenv("QBT_TEST_TORRENT", "https://example.org/missing.torrent")
    with pytest.raises(SystemExit, match="Couldn't read the test torrent"):
        run("03_lifecycle.py", monkeypatch=monkeypatch)
    monkeypatch.setenv("QBT_TEST_TORRENT", "ftp://example.org/x.torrent")
    with pytest.raises(SystemExit, match="magnet link or an http"):  # from torrentfile.identify
        run("03_lifecycle.py", monkeypatch=monkeypatch)
