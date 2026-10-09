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
    assert "CSRF check applies to API keys" in out
    assert "host header validation rejects" in out
    assert "method enforced (expected)" in out
    assert "| Probe | HTTP | Meaning |" in out


def test_00_probe_auth_csrf_skipped(env, monkeypatch, capsys):
    env.csrf_with_api_key = False
    run("00_probe_auth.py", monkeypatch=monkeypatch)
    assert "CSRF check skipped for API keys" in capsys.readouterr().out


def test_01_discover(env, monkeypatch, capsys, tmp_path):
    run("01_discover.py", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert API_KEY not in out
    assert "qBittorrent : v5.2.3" in out and "WebAPI      : 2.15.1" in out
    assert "5 in total" in out
    assert "stoppedDL" in out and "stoppedUP" in out
    assert "fields not in the wiki : none" in out
    assert "sandbox tag 'poc': not created yet" in out

    samples = tmp_path / "out" / "samples"
    torrents = json.loads((samples / "torrents_info.json").read_text())
    assert len(torrents) == 5
    raw = (samples / "torrents_info.json").read_text()
    for t in env.torrents:  # no real names, hashes or paths leak into the samples
        assert t["name"] not in raw and t["hash"] not in raw and t["save_path"] not in raw
    assert {t["name"] for t in torrents} == {f"torrent-{i:03d}" for i in range(1, 6)}


def test_01_discover_reports_new_fields(env, monkeypatch, capsys):
    for t in env.torrents:
        t["has_metadata"] = True
    env.torrents[0]["state"] = "brandNewState"
    run("01_discover.py", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "fields not in the wiki : has_metadata" in out
    assert "undocumented states    : brandNewState" in out
