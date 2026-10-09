"""Redaction: nothing private may reach out/samples/ or pasted example output."""

from qbittorrent_poc import samples


def test_tracker_host_drops_passkeys():
    assert samples.tracker_host("https://tracker.example.org:443/a1b2c3passkey/announce") == "https://tracker.example.org"
    assert samples.tracker_host("** [DHT] **") == "** [DHT] **"
    assert samples.tracker_host("not a url") == samples.REDACTED


def test_mask_ips():
    text = "Detected external IP. IP: 203.0.113.7, peer [2001:db8:0:0:1:0:0:1]"
    masked = samples.mask_ips(text)
    assert "203.0.113.7" not in masked and "2001:db8" not in masked
    assert masked.count("<ip>") == 2


def test_peers_lose_ips_and_keys():
    sync = {"rid": 3, "peers": {"198.51.100.1:51413": {"ip": "198.51.100.1", "port": 51413, "client": "x"}},
            "peers_removed": ["198.51.100.2:6881"]}
    clean = samples.peers(sync)
    assert "198.51.100" not in str(clean)
    assert clean["peers"]["peer-001"]["client"] == "x"


def test_maindata_redacts_torrents_and_external_ip():
    sync = {"rid": 1, "torrents": {"ab" * 20: {"name": "secret.iso", "save_path": "/data/x", "size": 5}},
            "torrents_removed": ["cd" * 20],
            "server_state": {"last_external_address_v4": "203.0.113.7", "dht_nodes": 3}}
    clean = str(samples.maindata(sync))
    for secret in ("secret.iso", "/data/x", "ab" * 20, "cd" * 20, "203.0.113.7"):
        assert secret not in clean
    assert "'size': 5" in clean and "'dht_nodes': 3" in clean


def test_files_keep_extension_only():
    assert samples.files([{"name": "Show/Show.S01E01.mkv", "size": 1}]) == [{"name": "file-001.mkv", "size": 1}]


def test_empty_values_stay_empty():
    assert samples.redact_keys({"comment": "", "save_path": None, "tracker": "x"}, samples.TORRENT_SECRETS) == {
        "comment": "", "save_path": None, "tracker": samples.REDACTED}
