import time

import pytest

from qbittorrent_poc import QbtClient, WebUI

from .fake_qbt import API_KEY, HOST, PORT, FakeQbt


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Examples wait between sync calls; tests don't need to."""
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


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
