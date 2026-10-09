import hashlib

import pytest

from qbittorrent_poc.torrentfile import TorrentFileError, encode, parse

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
