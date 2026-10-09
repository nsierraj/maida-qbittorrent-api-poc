"""Run the example scripts end to end against the fake server (the real NAS runs are manual)."""

import json
import runpy
import sys
from pathlib import Path

import pytest

from qbittorrent_poc import config

from .fake_qbt import API_KEY, HOST, PORT

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def env(qbt, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)  # never read the real .env
    for key, value in {
        "QBT_HOST": HOST, "QBT_PORT": str(PORT), "QBT_API_KEY": API_KEY,
        "QBT_SANDBOX_TAG": "poc", "QBT_POC_OUT": str(tmp_path / "out"),
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
