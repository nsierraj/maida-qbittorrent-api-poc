"""Example 0: how does this qBittorrent treat API keys and request headers?

Run this once, before anything else. It answers questions the wiki doesn't:
- Is the API key accepted as `Authorization: Bearer <key>`?
- Does the Referer/Origin check (CSRF protection) still apply to API key requests?
- Does Host header validation reject a container name such as `gluetun` (matters for Stage 5)?

Run it ONCE. Two probes send a missing and a wrong key on purpose. qBittorrent bans an IP for
web_ui_ban_duration (default 1 hour) after web_ui_max_auth_fail_count (default 5) failed
attempts; if API key failures count toward that limit, re-running this a few times in a row
locks you out of the WebUI until the ban expires. Whether they count is worth recording too.

Read-only: every probe is a GET of app/version or app/webapiVersion, plus one POST to a GET
endpoint (expected to be refused). Copy the result table into docs/qbittorrent/webui-api.md §8.
"""

from __future__ import annotations

import requests

from qbittorrent_poc import Settings
from qbittorrent_poc.config import mask

PROBES = [
    # (label, method, endpoint, extra headers, use key, how to read the result)
    ("API key, no other headers", "GET", "app/webapiVersion", {}, "key",
     {200: "key accepted"}),
    ("No key", "GET", "app/webapiVersion", {}, "none",
     {403: "auth required (expected)", 200: "WARNING: no auth needed (bypass for this subnet?)"}),
    ("Wrong key", "GET", "app/webapiVersion", {}, "wrong",
     {403: "wrong key refused (expected)", 401: "wrong key refused (401)"}),
    ("Key + matching Referer", "GET", "app/version", {"Referer": "{base}/"}, "key",
     {200: "same-origin Referer is fine"}),
    ("Key + foreign Referer", "GET", "app/version", {"Referer": "http://evil.example/"}, "key",
     {200: "CSRF check skipped for API keys", 401: "CSRF check applies to API keys"}),
    ("Key + foreign Origin", "GET", "app/version", {"Origin": "http://evil.example"}, "key",
     {200: "CSRF check skipped for API keys", 401: "CSRF check applies to API keys"}),
    ("Key + Host: gluetun:<port>", "GET", "app/version", {"Host": "gluetun:{port}"}, "key",
     {200: "container names accepted (validation off, or the name is in 'Server domains')",
      401: "host header validation rejects names not in 'Server domains'"}),
    ("Key + POST to a GET endpoint", "POST", "app/version", {}, "key",
     {405: "GET endpoints refuse POST", 200: "GET endpoints also accept POST"}),
]


def main() -> None:
    settings = Settings.from_env()
    base = f"http://{settings.host}:{settings.port}"
    print(f"Probing {base} with API key {mask(settings.api_key)}\n")
    print(f"  {'probe':<32} {'HTTP':>4}  body / meaning")
    results = []
    for label, method, endpoint, extra, key, meanings in PROBES:
        headers = {k: v.format(base=base, port=settings.port) for k, v in extra.items()}
        if key == "key":
            headers["Authorization"] = f"Bearer {settings.api_key}"
        elif key == "wrong":
            headers["Authorization"] = "Bearer qbt_not-a-real-key"
        try:
            resp = requests.request(method, f"{base}/api/v2/{endpoint}", headers=headers, timeout=15)
        except requests.RequestException as e:
            print(f"  {label:<32} {'-':>4}  cannot connect: {e}")
            raise SystemExit(1) from e
        body = resp.text.strip()[:30]
        meaning = meanings.get(resp.status_code, "unexpected, note it in the errata")
        results.append((label, resp.status_code, meaning))
        print(f"  {label:<32} {resp.status_code:>4}  {body!r}: {meaning}")

    print("\nMarkdown for docs/qbittorrent/webui-api.md §8:\n")
    print("| Probe | HTTP | Meaning |\n| --- | --- | --- |")
    for label, status, meaning in results:
        print(f"| {label} | {status} | {meaning} |")


if __name__ == "__main__":
    main()
