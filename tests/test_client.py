import pytest

from qbittorrent_poc import QbtClient, QbtError

from .fake_qbt import API_KEY, HOST, PORT


def test_bearer_key_is_sent_and_text_is_decoded(qbt, client):
    assert client.get("app/webapiVersion") == "2.15.1"
    assert client.session.headers["Authorization"] == f"Bearer {API_KEY}"


def test_json_is_decoded(client):
    assert client.get("app/buildInfo")["bitness"] == 64


def test_wrong_key_is_an_auth_error(qbt):
    c = QbtClient(HOST, PORT, api_key="qbt_wrong")
    with pytest.raises(QbtError) as exc:
        c.get("app/version")
    assert exc.value.status == 403 and exc.value.is_auth_error
    assert "API key" in str(exc.value)


def test_api_key_is_required():
    with pytest.raises(ValueError):
        QbtClient(HOST, PORT, api_key="")


def test_key_not_in_repr(client):
    assert API_KEY not in repr(client)


def test_wrong_method_maps_405(client):
    with pytest.raises(QbtError) as exc:
        client.post("app/version")
    assert exc.value.status == 405


def test_booleans_are_lowercase_and_none_is_dropped(qbt, client):
    client.get("torrents/info", reverse=True, sort="name", category=None)
    _, endpoint, params = qbt.requests[-1]
    assert endpoint == "torrents/info"
    assert params == {"reverse": "true", "sort": "name"}


def test_host_header_validation_rejects_names(qbt):
    c = QbtClient("gluetun", PORT, api_key=API_KEY)
    with pytest.raises(QbtError) as exc:
        c.get("app/version")
    assert exc.value.status == 401
    qbt.server_domains.add("gluetun")
    assert c.get("app/version") == "v5.2.3"
