"""Human-readable formatting for sizes, speeds, durations and timestamps."""

from __future__ import annotations

from datetime import datetime, timezone

INFINITE_ETA = 8_640_000  # qBittorrent's "∞" ETA (100 days)
_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")


def size(n: int | float) -> str:
    if n is None or n < 0:
        return "unknown"
    value = float(n)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def speed(n: int | float) -> str:
    return f"{size(n)}/s"


def limit(n: int) -> str:
    """Rate limits: 0 or -1 mean unlimited."""
    return "unlimited" if n is None or n <= 0 else speed(n)


def duration(seconds: int) -> str:
    if seconds is None or seconds < 0 or seconds >= INFINITE_ETA:
        return "∞"
    minutes, s = divmod(int(seconds), 60)
    hours, m = divmod(minutes, 60)
    days, h = divmod(hours, 24)
    if days:
        return f"{days}d {h}h"
    if hours:
        return f"{hours}h {m}m"
    if minutes:
        return f"{minutes}m {s}s"
    return f"{s}s"


def timestamp(epoch: int) -> str:
    if not epoch or epoch < 0:
        return "never"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def percent(fraction: float) -> str:
    return f"{fraction * 100:.1f}%"
