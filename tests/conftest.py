import time

import pytest

from qbittorrent_poc import QbtClient, WebUI

from .fake_qbt import API_KEY, HOST, PORT, FakeQbt


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Examples wait between sync calls; tests don't need to."""
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """No real DNS in tests: every name resolves to a public address unless a test says otherwise."""
    from qbittorrent_poc import torrentfile

    table: dict[str, list[str]] = {}
    monkeypatch.setattr(torrentfile, "_resolve", lambda host, port: table.get(host, ["151.101.2.132"]))
    return table


@pytest.fixture
def qbt(monkeypatch) -> FakeQbt:
    fake = FakeQbt()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def client(qbt) -> QbtClient:
    c = QbtClient(HOST, PORT, api_key=API_KEY)
    yield c
    c.close()


@pytest.fixture
def api(client) -> WebUI:
    return WebUI(client)
