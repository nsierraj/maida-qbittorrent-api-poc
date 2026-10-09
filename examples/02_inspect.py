"""Example 2: everything the API says about one torrent, plus incremental sync and the log.

    uv run examples/02_inspect.py              # the most recently added torrent
    uv run examples/02_inspect.py ubuntu       # name contains "ubuntu" (case-insensitive)
    uv run examples/02_inspect.py 1a2b3c       # hash prefix

Read-only. Properties -> files -> trackers -> peers -> sync/maindata (full, then a delta after
--wait seconds) -> log -> fields that differ from the reference sets in qbittorrent_poc.fields.
Console output hides secrets but not content: tracker URLs show only scheme://host (private
trackers embed passkeys), peers are summarized without IPs, and IPs in log lines are masked,
but the torrent name, file names and log messages are shown so you can tell what you're
looking at. Trim them before pasting if you prefer. The samples in out/samples/ drop them too.
"""

from __future__ import annotations

import argparse
import time
from collections import Counter

from qbittorrent_poc import QbtError, Settings, WebUI, connect, fields, fmt, samples
from qbittorrent_poc.config import mask

SERVER_STATE_SHOWN = ("free_space_on_disk", "alltime_dl", "alltime_ul", "global_ratio",
                      "total_peer_connections", "queueing", "use_alt_speed_limits")


def pick(api: WebUI, query: str | None) -> dict:
    if query:
        try:
            torrent_hash = api.resolve_hash(query)
        except ValueError as e:
            raise SystemExit(str(e)) from e
        return api.list_torrents(hashes=[torrent_hash])[0]
    newest = api.list_torrents(sort="added_on", reverse=True, limit=1)
    if not newest:
        raise SystemExit("No torrents on this server; add one in the WebUI and run again.")
    return newest[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", nargs="?", help="hash, hash prefix, or part of the name")
    parser.add_argument("--wait", type=float, default=3.0, help="seconds between the two maindata calls")
    parser.add_argument("--files", type=int, default=15, help="how many files to list (largest first)")
    args = parser.parse_args()

    settings = Settings.from_env()
    print(f"Connecting to http://{settings.host}:{settings.port} with API key {mask(settings.api_key)}")

    with connect(settings) as client:
        api = WebUI(client)
        t = pick(api, args.query)
        h = t["hash"]
        print(f"\n[1] Torrent: {t['name']}")
        print(f"    hash {h[:12]}…  state {t['state']}  {fmt.percent(t['progress'])} of {fmt.size(t['size'])}"
              f"  category {t['category'] or '-'}  tags {t['tags'] or '-'}")

        props = api.properties(h)
        print("\n[2] Properties (torrents/properties)")
        print(f"    save path      : {props.get('save_path')}  (container path)")
        print(f"    added          : {fmt.timestamp(props.get('addition_date'))}"
              f"   completed: {fmt.timestamp(props.get('completion_date'))}")
        print(f"    pieces         : {props.get('pieces_have')}/{props.get('pieces_num')}"
              f" × {fmt.size(props.get('piece_size'))}   wasted {fmt.size(props.get('total_wasted'))}")
        print(f"    transferred    : down {fmt.size(props.get('total_downloaded'))}"
              f"  up {fmt.size(props.get('total_uploaded'))}  ratio {props.get('share_ratio', 0):.3f}")
        print(f"    swarm          : seeds {props.get('seeds')}/{props.get('seeds_total')}"
              f"  peers {props.get('peers')}/{props.get('peers_total')}"
              f"  connections {props.get('nb_connections')}/{props.get('nb_connections_limit')}")
        print(f"    speed avg      : down {fmt.speed(props.get('dl_speed_avg', 0))}"
              f"  up {fmt.speed(props.get('up_speed_avg', 0))}   eta {fmt.duration(props.get('eta'))}")
        print(f"    time           : active {fmt.duration(props.get('time_elapsed'))}"
              f"  seeding {fmt.duration(props.get('seeding_time'))}")
        print(f"    private        : {props.get('private', props.get('isPrivate'))}")

        file_rows = api.files(h)
        skipped = [f for f in file_rows if f["priority"] == 0]
        print(f"\n[3] Files (torrents/files): {len(file_rows)} files, {len(skipped)} skipped")
        for f in sorted(file_rows, key=lambda f: f["size"], reverse=True)[: args.files]:
            prio = fields.FILE_PRIORITIES.get(f["priority"], str(f["priority"]))
            print(f"    {fmt.size(f['size']):>10}  {fmt.percent(f['progress']):>6}  {prio:<7}  {f['name'][:70]}")
        if len(file_rows) > args.files:
            print(f"    … {len(file_rows) - args.files} more (--files N to show more)")

        tracker_rows = api.trackers(h)
        print(f"\n[4] Trackers (torrents/trackers): {len(tracker_rows)} rows (tier -1 = DHT/PeX/LSD)")
        for tr in tracker_rows:
            status = fields.TRACKER_STATUSES.get(tr["status"], str(tr["status"]))
            print(f"    tier {tr['tier']:>2}  {status:<13}  seeds {tr['num_seeds']:>5}  leeches {tr['num_leeches']:>5}"
                  f"  {samples.tracker_host(tr['url'])}  {samples.mask_ips(tr.get('msg', ''))}")

        peer_sync = api.peers(h)
        peer_rows = list(peer_sync.get("peers", {}).values())
        print(f"\n[5] Peers (sync/torrentPeers): {len(peer_rows)} connected"
              + ("  (the torrent is stopped)" if t["state"].startswith("stopped") else ""))
        if peer_rows:
            for label, key in (("clients", "client"), ("countries", "country_code"), ("connection", "connection")):
                top = Counter(p.get(key) or "?" for p in peer_rows).most_common(5)
                print(f"    {label:<11}: " + ", ".join(f"{k} ×{n}" for k, n in top))

        full = api.maindata()
        state = full.get("server_state", {})
        print(f"\n[6] Sync (sync/maindata): rid {full.get('rid')}, full_update {full.get('full_update')},"
              f" {len(full.get('torrents', {}))} torrents, {len(full.get('categories', {}))} categories,"
              f" {len(full.get('tags', []))} tags, {len(state)} server_state keys")
        for key in SERVER_STATE_SHOWN:
            if key in state:
                value = state[key]
                shown = fmt.size(value) if key in ("free_space_on_disk", "alltime_dl", "alltime_ul") else value
                print(f"    {key:<24} {shown}")
        print(f"    waiting {args.wait:g}s, then asking for changes since rid {full.get('rid')} …")
        time.sleep(args.wait)
        delta = api.maindata(full.get("rid", 0))
        changed = {k: v for k, v in delta.items() if k != "rid"}
        print(f"    delta rid {delta.get('rid')}: top-level keys {sorted(changed) or 'none (nothing changed)'}")
        for th, row in delta.get("torrents", {}).items():
            print(f"      torrent {th[:8]}… changed: {', '.join(sorted(row))}")
        if "server_state" in delta:
            print(f"      server_state changed: {', '.join(sorted(delta['server_state']))}")

        log = api.main_log()
        by_type = Counter(fields.LOG_TYPES.get(e["type"], str(e["type"])) for e in log)
        print(f"\n[7] Log (log/main): {len(log)} entries: "
              + ", ".join(f"{k} {n}" for k, n in sorted(by_type.items())))
        problems = [e for e in log if e["type"] >= 4][-5:]
        for e in problems:
            print(f"    {fmt.timestamp(e['timestamp'])}  {fields.LOG_TYPES.get(e['type'])}: "
                  f"{samples.mask_ips(e['message'])[:100]}")
        newer = api.main_log(last_known_id=log[-1]["id"]) if log else []
        print(f"    entries after id {log[-1]['id'] if log else '-'}: {len(newer)} (last_known_id works"
              f" {'as documented' if not newer else 'unexpectedly'})")

        print("\n[8] Server vs reference (qbittorrent_poc.fields)")
        checks = {
            "torrents/info": (t, fields.TORRENT_FIELDS),
            "sync/maindata torrents": (list(full.get("torrents", {}).values()), fields.MAINDATA_TORRENT_FIELDS),
            "torrents/properties": (props, fields.PROPERTIES_FIELDS),
            "torrents/files": (file_rows, fields.FILE_FIELDS),
            "torrents/trackers": (tracker_rows, fields.TRACKER_FIELDS),
            "sync/torrentPeers peers": (peer_rows, fields.PEER_FIELDS),
            "sync/maindata server_state": (state, fields.SERVER_STATE_FIELDS),
            "log/main": (log, fields.LOG_FIELDS),
        }
        for label, (rows, ref) in checks.items():
            if not rows:
                print(f"    {label:<27} no data to compare")
                continue
            new, missing = fields.diff_fields(rows, ref)
            print(f"    {label:<27} new: {', '.join(new) or 'none'}")
            print(f"    {'':<27} not sent: {', '.join(missing) or 'none'}")
        top_level = sorted(full)
        print(f"    sync/maindata top level     {', '.join(top_level)}")
        print(f"    sync/torrentPeers top level {', '.join(sorted(peer_sync))}")

        target = samples.write_samples({
            "properties.json": samples.properties(props),
            "files.json": samples.files(file_rows),
            "trackers.json": samples.trackers(tracker_rows),
            "torrent_peers.json": samples.peers(peer_sync),
            "maindata_full.json": samples.maindata(full),
            "maindata_delta.json": samples.maindata(delta),
            "log_main.json": samples.log(log[-20:]),
        })
        print(f"\n[9] Sanitized samples written to {target}/")

        print("\n[10] Errors")
        try:
            api.properties("0" * 40)
            print("    unknown hash: torrents/properties answered 200 (note it in the errata)")
        except QbtError as e:
            print(f"    unknown hash: torrents/properties -> HTTP {e.status} (as documented: 404)"
                  if e.status == 404 else f"    unknown hash: HTTP {e.status} (note it in the errata)")


if __name__ == "__main__":
    main()
