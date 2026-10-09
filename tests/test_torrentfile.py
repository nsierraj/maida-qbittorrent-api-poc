import hashlib

import pytest

from qbittorrent_poc.torrentfile import TorrentFileError, check_public_url, encode, fetch, parse

INFO = {"length": 1000, "name": "x.iso", "piece length": 16384, "pieces": b"\x00" * 20}


def test_v1_hash_is_sha1_of_the_raw_info_dict():
    data = encode({"announce": "https://t.example/a", "info": INFO, "url-list": "https://seed.example/"})
    t = parse(data)
    assert t.info_hash == hashlib.sha1(encode(INFO)).hexdigest()
    assert (t.name, t.size, t.webseeds) == ("x.iso", 1000, ("https://seed.example/",))


def test_multi_file_size():
    info = {"name": "dir", "piece length": 16384, "pieces": b"\x00" * 20,
            "files": [{"length": 3, "path": ["a"]}, {"length": 4, "path": ["b"]}]}
    assert parse(encode({"info": info})).size == 7


def test_v2_only_uses_truncated_sha256():
    info = {"meta version": 2, "name": "v2", "piece length": 16384, "file tree": {}}
    t = parse(encode({"info": info}))
    assert t.info_hash == hashlib.sha256(encode(info)).hexdigest()[:40] and t.size is None


def test_hybrid_uses_sha1():
    info = {**INFO, "meta version": 2, "file tree": {}}
    assert parse(encode({"info": info})).info_hash == hashlib.sha1(encode(info)).hexdigest()


@pytest.mark.parametrize("data", [b"", b"<html>not a torrent</html>", b"d4:infoi1ee", b"d3:abc", encode({"a": 1})])
def test_rejects_non_torrents(data):
    with pytest.raises(TorrentFileError):
        parse(data)


def test_encode_rejects_bools():
    with pytest.raises(TypeError):
        encode(True)


def test_raw_bytes_are_kept_for_upload():
    data = encode({"info": INFO})
    assert parse(data).raw == data


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "172.18.0.2", "192.168.1.50", "169.254.169.254", "100.64.0.1",
    "0.0.0.0", "::1", "fd00::1", "fe80::1%en0", "224.0.0.1",
])
def test_internal_addresses_are_refused(dns, address):
    dns["evil.example"] = [address]
    with pytest.raises(TorrentFileError, match="private or internal"):
        check_public_url("https://evil.example/x.torrent")


def test_any_internal_address_among_several_is_refused(dns):
    dns["mixed.example"] = ["151.101.2.132", "192.168.1.10"]
    with pytest.raises(TorrentFileError):
        check_public_url("http://mixed.example/x.torrent")


@pytest.mark.parametrize("url", ["ftp://example.org/x.torrent", "file:///etc/passwd", "http:///x", "/etc/passwd"])
def test_only_http_urls(url):
    with pytest.raises(TorrentFileError, match="http"):
        check_public_url(url)


def test_ip_literals_are_checked_too():
    with pytest.raises(TorrentFileError):
        check_public_url("http://127.0.0.1:5000/webapi/entry.cgi")


def test_unresolvable_host(monkeypatch):
    import socket

    from qbittorrent_poc import torrentfile

    def fail(host, port):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(torrentfile, "_resolve", fail)
    with pytest.raises(TorrentFileError, match="Can't resolve"):
        check_public_url("https://nowhere.invalid/x.torrent")


def test_redirects_are_followed_and_each_hop_checked(qbt, dns):
    from .fake_qbt import ARCH_HASH, ARCH_URL

    qbt.web["https://short.example/arch"] = ARCH_URL
    assert fetch("https://short.example/arch").info_hash == ARCH_HASH
    qbt.web["https://short.example/dsm"] = "http://nas.lan:5000/webapi/entry.cgi"
    dns["nas.lan"] = ["192.168.1.50"]
    with pytest.raises(TorrentFileError, match="192.168.1.50"):
        fetch("https://short.example/dsm")
    assert "http://nas.lan:5000/webapi/entry.cgi" not in qbt.downloads  # refused before connecting


def test_redirect_loops_stop(qbt):
    qbt.web["https://loop.example/a"] = "https://loop.example/a"
    with pytest.raises(TorrentFileError, match="redirects"):
        fetch("https://loop.example/a")
