"""Example 1: what does this qBittorrent look like? Read-only.

Versions -> global transfer state -> torrents by state and by filter -> categories and tags ->
fields and states the server returns that the wiki doesn't list. Finally it saves sanitized
JSON samples to out/samples/ (gitignored) so the fake server in tests/ can follow the real one.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from qbittorrent_poc import FILTERS, TORRENT_FIELDS, TORRENT_STATES, Settings, WebUI, connect, fmt
from qbittorrent_poc.config import mask
from qbittorrent_poc.webui import split_tags

REDACT = {"name", "magnet_uri", "tracker", "save_path", "content_path", "download_path",
          "root_path", "comment", "infohash_v1", "infohash_v2", "hash"}


def sanitize(torrents: list[dict]) -> list[dict]:
    """Keep the structure and numbers; drop names, hashes, paths and tracker URLs."""
    out = []
    for i, t in enumerate(torrents, 1):
        clean = {k: ("<redacted>" if k in REDACT and v else v) for k, v in t.items()}
        clean["name"] = f"torrent-{i:03d}"
        clean["hash"] = f"{i:040x}"
        out.append(clean)
    return out


def main() -> None:
    settings = Settings.from_env()
    print(f"Connecting to http://{settings.host}:{settings.port} with API key {mask(settings.api_key)}")

    with connect(settings) as client:
        api = WebUI(client)

        print("\n[1] Versions (app/version, app/webapiVersion, app/buildInfo)")
        build = api.build_info()
        print(f"    qBittorrent : {api.app_version()}")
        print(f"    WebAPI      : {api.webapi_version()}")
        for key in sorted(build):
            print(f"    {key:<12}: {build[key]}")

        print("\n[2] Transfer state (transfer/info)")
        info = api.transfer_info()
        print(f"    connection  : {info.get('connection_status')}  (DHT nodes: {info.get('dht_nodes')})")
        print(f"    download    : {fmt.speed(info['dl_info_speed'])}  limit {fmt.limit(info['dl_rate_limit'])}"
              f"  session total {fmt.size(info['dl_info_data'])}")
        print(f"    upload      : {fmt.speed(info['up_info_speed'])}  limit {fmt.limit(info['up_rate_limit'])}"
              f"  session total {fmt.size(info['up_info_data'])}")
        print(f"    alt limits  : {'on' if api.alt_speed_limits_enabled() else 'off'}")
        print(f"    save path   : {api.default_save_path()}  (container path)")

        torrents = api.list_torrents()
        print(f"\n[3] Torrents (torrents/info): {len(torrents)} in total, "
              f"{fmt.size(sum(t['size'] for t in torrents))} selected")
        for state, count in Counter(t["state"] for t in torrents).most_common():
            print(f"    {state:<20} {count}")
        print("    by filter:")
        for flt in FILTERS:
            print(f"      {flt:<20} {len(api.list_torrents(flt))}")
        busy = api.list_torrents("active", sort="dlspeed", reverse=True, limit=5)
        if busy:
            print("    most active (sort=dlspeed, reverse, limit=5):")
            for t in busy:
                print(f"      {fmt.percent(t['progress']):>6}  down {fmt.speed(t['dlspeed']):>12}"
                      f"  up {fmt.speed(t['upspeed']):>12}  eta {fmt.duration(t['eta']):>7}  [{t['state']}]"
                      f"  {t['name'][:50]}")

        print("\n[4] Categories and tags (torrents/categories, torrents/tags)")
        categories, tags = api.categories(), api.tags()
        per_cat = Counter(t["category"] for t in torrents)
        per_tag = Counter(tag for t in torrents for tag in split_tags(t["tags"]))
        for name, cat in sorted(categories.items()):
            print(f"    category {name!r:<24} {per_cat.get(name, 0):>4} torrents  savePath={cat.get('savePath')!r}")
        print(f"    {'uncategorized':<33} {per_cat.get('', 0):>4} torrents")
        for tag in sorted(tags):
            print(f"    tag {tag!r:<29} {per_tag.get(tag, 0):>4} torrents")
        sandbox = settings.sandbox_tag
        print(f"    sandbox tag {sandbox!r}: {'exists' if sandbox in tags else 'not created yet'}, "
              f"{per_tag.get(sandbox, 0)} torrents")

        print("\n[5] Server vs wiki")
        seen_fields = set().union(*(t.keys() for t in torrents)) if torrents else set()
        extra = sorted(seen_fields - set(TORRENT_FIELDS))
        missing = sorted(set(TORRENT_FIELDS) - seen_fields) if torrents else []
        unknown_states = sorted({t["state"] for t in torrents} - set(TORRENT_STATES))
        print(f"    fields not in the wiki : {', '.join(extra) or 'none'}")
        print(f"    wiki fields not sent   : {', '.join(missing) or 'none'}")
        print(f"    undocumented states    : {', '.join(unknown_states) or 'none'}")

        out_dir = Path(os.getenv("QBT_POC_OUT", "out")) / "samples"
        out_dir.mkdir(parents=True, exist_ok=True)
        samples = {
            "app.json": {"version": api.app_version(), "webapiVersion": api.webapi_version(),
                         "buildInfo": build},
            "transfer_info.json": info,
            "torrents_info.json": sanitize(torrents),
            "categories.json": categories,
            "tags.json": tags,
        }
        for name, data in samples.items():
            (out_dir / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        print(f"\n[6] Sanitized samples written to {out_dir}/ (names, hashes, paths, trackers redacted)")


if __name__ == "__main__":
    main()
