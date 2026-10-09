from qbittorrent_poc import fmt


def test_size_and_speed():
    assert fmt.size(512) == "512 B"
    assert fmt.size(1536) == "1.5 KiB"
    assert fmt.size(4_000_000_000) == "3.7 GiB"
    assert fmt.size(-1) == "unknown"
    assert fmt.speed(2_500_000) == "2.4 MiB/s"
    assert fmt.limit(0) == "unlimited" and fmt.limit(-1) == "unlimited"


def test_duration():
    assert fmt.duration(8_640_000) == "∞"
    assert fmt.duration(59) == "59s"
    assert fmt.duration(3_700) == "1h 1m"
    assert fmt.duration(90_000) == "1d 1h"


def test_timestamp_and_percent():
    assert fmt.timestamp(0) == "never"
    assert fmt.timestamp(1_790_000_000).endswith("UTC")
    assert fmt.percent(0.421) == "42.1%"
