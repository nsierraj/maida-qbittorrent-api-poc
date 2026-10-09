import pytest

from qbittorrent_poc import Settings, config, connect

from .fake_qbt import API_KEY, HOST


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)  # never read the real .env
    for key in ("QBT_HOST", "QBT_PORT", "QBT_API_KEY", "QBT_SANDBOX_TAG", "QBT_SANDBOX_SAVEPATH"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_missing_settings_exit(env):
    with pytest.raises(SystemExit, match="QBT_HOST, QBT_API_KEY"):
        Settings.from_env()


def test_defaults(env):
    env.setenv("QBT_HOST", HOST)
    env.setenv("QBT_API_KEY", API_KEY)
    s = Settings.from_env()
    assert (s.port, s.sandbox_tag, s.sandbox_savepath) == (8090, "poc", None)
    assert API_KEY not in repr(s)


def test_bad_port(env):
    env.setenv("QBT_HOST", HOST)
    env.setenv("QBT_API_KEY", API_KEY)
    env.setenv("QBT_PORT", "eighty")
    with pytest.raises(SystemExit, match="QBT_PORT"):
        Settings.from_env()


def test_connect_ok(qbt):
    client = connect(Settings(HOST, 8090, API_KEY))
    assert client.get("app/version") == "v5.2.3"


def test_connect_wrong_key_explains(qbt):
    with pytest.raises(SystemExit, match="Check QBT_API_KEY"):
        connect(Settings(HOST, 8090, "qbt_wrong"))


def test_connect_unreachable_explains(monkeypatch):
    import requests

    def refuse(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests.Session, "request", refuse)
    with pytest.raises(SystemExit, match="Cannot reach"):
        connect(Settings(HOST, 8090, API_KEY))
