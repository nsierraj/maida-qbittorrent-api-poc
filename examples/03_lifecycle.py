"""Example 3: change things, but only inside the sandbox.

    uv run examples/03_lifecycle.py             # full lifecycle, removes everything at the end
    uv run examples/03_lifecycle.py --keep      # stop before deleting, to look at it in the WebUI
    uv run examples/03_lifecycle.py --cleanup   # delete every torrent tagged QBT_SANDBOX_TAG

Adds a legal test torrent (QBT_TEST_TORRENT: a .torrent URL or a magnet link; default the
Arch Linux 2026.10.01 ISO) STOPPED, tagged
QBT_SANDBOX_TAG, into QBT_SANDBOX_SAVEPATH. Then: start for --run-seconds -> stop -> recheck
-> category -> tags -> rename -> move -> a deliberately refused change on a torrent outside the
sandbox -> delete with files. Every change goes through Sandbox/TorrentPolicy, which refuses
locally (no request sent) anything not tagged QBT_SANDBOX_TAG or outside the save path.

It also answers what the wiki leaves open: whether torrents/add honors `stopped` (5.x) or
`paused` (4.x), what torrents/add returns, and whether POST-only endpoints refuse GET.
"""

from __future__ import annotations

import argparse
import os
import time
from urllib.parse import parse_qs, urlsplit

import requests

from qbittorrent_poc import PolicyError, QbtError, Sandbox, Settings, TorrentPolicy, WebUI, connect, fmt
from qbittorrent_poc.config import mask
from qbittorrent_poc.torrentfile import MAX_TORRENT_BYTES, TorrentFileError, parse
from qbittorrent_poc.webui import magnet_hash, split_tags

ARCH = "https://fastly.mirror.pkgbuild.com/iso/2026.10.01/archlinux-2026.10.01-x86_64.iso.torrent"
HELPER_TAG = "poc-extra"
# States a torrent passes through right after torrents/add, before it settles (seen on 5.2.3).
TRANSIENT = {"checkingResumeData", "allocating", "checkingDL", "checkingUP", "moving", "unknown"}


def identify(url: str) -> tuple[str, str]:
    """(info hash, name) before adding: from the magnet link itself, or by fetching the .torrent
    file here and hashing its info dictionary (qBittorrent fetches it again when adding)."""
    if url.startswith("magnet:"):
        names = parse_qs(urlsplit(url).query).get("dn", [])
        h = magnet_hash(url)
        return h, names[0] if names else h
    if not url.startswith(("http://", "https://")):
        raise SystemExit("QBT_TEST_TORRENT must be a magnet link or an http(s) URL of a .torrent file.")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        if len(resp.content) > MAX_TORRENT_BYTES:
            raise TorrentFileError("too large")
        meta = parse(resp.content)
    except (requests.RequestException, TorrentFileError) as e:
        raise SystemExit(f"Couldn't read the test torrent at {url}: {e}") from e
    size = fmt.size(meta.size) if meta.size is not None else "unknown size"
    print(f"Test torrent: {meta.name}, {size}, {len(meta.webseeds)} web seeds, hash {meta.info_hash[:12]}…")
    return meta.info_hash, meta.name


def show(row: dict | None) -> str:
    if row is None:
        return "gone"
    meta = "metadata" if row.get("has_metadata") else "no metadata yet"
    return (f"{row['state']:<11} {fmt.percent(row['progress']):>6} of {fmt.size(row['size']):>9}"
            f"  down {fmt.speed(row['dlspeed']):>11}  {meta}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="stop and keep the torrent instead of deleting it")
    parser.add_argument("--cleanup", action="store_true", help="only delete sandbox leftovers")
    parser.add_argument("--run-seconds", type=float, default=8, help="how long to let it run")
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.sandbox_savepath:
        raise SystemExit("Set QBT_SANDBOX_SAVEPATH (a container path such as /data/torrents/poc) in .env.")
    url = (os.getenv("QBT_TEST_TORRENT") or "").strip() or ARCH
    tag, root = settings.sandbox_tag, settings.sandbox_savepath
    print(f"Connecting to http://{settings.host}:{settings.port} with API key {mask(settings.api_key)}")
    print(f"Sandbox: tag {tag!r}, save path {root}")

    with connect(settings) as client:
        api = WebUI(client)
        box = Sandbox(api, TorrentPolicy(tag, root, allow_writes=True, allow_delete=True))

        if args.cleanup:
            removed = box.cleanup(extra_tags=[HELPER_TAG], categories=[tag])
            print(f"\nRemoved {len(removed['torrents'])} sandbox torrent(s) with their files, "
                  f"tags {removed['tags'] or '-'}, categories {removed['categories'] or '-'}.")
            return

        h, _ = identify(url)
        existing = api.list_torrents(hashes=[h])
        if existing and tag not in split_tags(existing[0]["tags"]):
            raise SystemExit(f"{existing[0]['name']} is already in qBittorrent without the {tag!r} tag. "
                             "It isn't the sandbox's to touch; pick another QBT_TEST_TORRENT.")
        if existing:
            raise SystemExit("A sandbox copy of this torrent is still there; run with --cleanup first.")

        try:
            run(api, box, h, url, tag, root, args)
        except BaseException:
            print("\n!! Stopped early. Stopping the sandbox torrent; run with --cleanup to remove it.")
            try:
                box.stop([h])
            except (QbtError, PolicyError):
                pass
            raise


def poll(row: dict | None) -> None:
    print(f"      {show(row)}")


def run(api: WebUI, box: Sandbox, h: str, url: str, tag: str, root: str, args: argparse.Namespace) -> None:
    print(f"\n[1] Add stopped (torrents/add: stopped, autoTMM=false, useDownloadPath=false), hash {h[:12]}…")
    answer = box.add([url], savepath=root, stopped=True)
    print(f"    server answered: {answer!r}")
    # A URL add answers before qBittorrent has fetched the .torrent file; allow for that.
    row = box.wait_for(h, lambda r: r is not None, timeout=60)
    print(f"    appeared: {show(row)}")
    if row["state"] in TRANSIENT:
        row = box.wait_for(h, lambda r: r["state"] not in TRANSIENT, timeout=60, on_poll=poll)
    honored = row["state"].startswith("stopped")
    print(f"    settled : {show(row)}")
    print(f"    tags {row['tags']!r}, save path {row['save_path']}, download path "
          f"{row.get('download_path') or '-'}, auto_tmm {row.get('auto_tmm')}")
    try:
        box.policy.check_row(row)
    except PolicyError as e:
        print(f"    !! the server put it OUTSIDE the sandbox (note it in the errata): {e}")
        print("       Deleting it before anything is downloaded.")
        box.delete([h], delete_files=True)
        box.wait_for(h, lambda r: r is None, timeout=30)
        raise SystemExit(1) from e
    print(f"    stop-on-add: {'honored' if honored else 'IGNORED (note it in the errata); stopping now'}")
    if not honored:
        box.stop([h])

    print(f"\n[2] Start (torrents/start), let it run {args.run_seconds:g}s")
    box.start([h])
    deadline = time.monotonic() + args.run_seconds
    while time.monotonic() < deadline:
        time.sleep(2)
        print(f"      {show(api.list_torrents(hashes=[h])[0])}")

    print("\n[3] Stop. First a GET on the POST-only torrents/stop, to see whether the method is enforced")
    try:
        api.client.get("torrents/stop", hashes=h)
        print("    GET torrents/stop -> 200: POST-only endpoints accept GET too (note it in the errata)")
    except QbtError as e:
        print(f"    GET torrents/stop -> HTTP {e.status}" + (" (method enforced)" if e.status == 405 else ""))
    box.stop([h])
    row = box.wait_for(h, lambda r: r["state"].startswith("stopped"), timeout=30, on_poll=poll)

    print("\n[4] Recheck (torrents/recheck), waiting for the check to finish")
    box.recheck([h])
    time.sleep(1)
    row = box.wait_for(h, lambda r: not r["state"].startswith("checking"), timeout=180, interval=2, on_poll=poll)
    print(f"    checked: {fmt.size(row['completed'])} verified ({row['state']})")
    if not row["state"].startswith("stopped"):
        print("    recheck resumed it (note it in the errata); stopping it again")
        box.stop([h])
        box.wait_for(h, lambda r: r["state"].startswith("stopped"), timeout=30)

    print(f"\n[5] Category {tag!r} (createCategory if missing, setCategory)")
    created = box.ensure_category(tag, root)
    box.set_category([h], tag)
    row = api.list_torrents(hashes=[h])[0]
    print(f"    category {'created' if created else 'already existed'}; torrent category now {row['category']!r}")
    try:
        box.set_category([h], "no-such-category-poc")
    except QbtError as e:
        print(f"    unknown category -> HTTP {e.status} (documented: 409)")

    print(f"\n[6] Tags (addTags {HELPER_TAG!r}, removeTags, then try to remove {tag!r})")
    box.add_tags([h], [HELPER_TAG])
    print(f"    after add   : {api.list_torrents(hashes=[h])[0]['tags']!r}")
    box.remove_tags([h], [HELPER_TAG])
    print(f"    after remove: {api.list_torrents(hashes=[h])[0]['tags']!r}")
    try:
        box.remove_tags([h], [tag])
    except PolicyError as e:
        print(f"    refused locally, nothing sent: {e}")

    print("\n[7] Rename (torrents/rename; the display name only)")
    box.rename(h, "poc-renamed-test")
    print(f"    name now {api.list_torrents(hashes=[h])[0]['name']!r}")

    target = f"{root}/moved"
    print(f"\n[8] Move (torrents/setLocation) to {target}")
    box.set_location([h], target)
    row = box.wait_for(h, lambda r: r["save_path"].rstrip("/") == target, timeout=60, on_poll=poll)
    print(f"    save path now {row['save_path']}")
    try:
        box.set_location([h], "/data/torrents")
    except PolicyError as e:
        print(f"    move outside the sandbox refused locally: {e}")

    print("\n[9] The sandbox boundary: try to stop a torrent that isn't tagged")
    outsider = next((t for t in api.list_torrents() if tag not in split_tags(t["tags"])), None)
    if outsider is None:
        print("    every torrent is in the sandbox; nothing to show")
    else:
        try:
            box.stop([outsider["hash"]])
            print("    !! it was NOT refused; stop and report this")
        except PolicyError as e:
            print(f"    refused locally, nothing sent: {str(e).split(' Not tagged')[0]}")

    if args.keep:
        print(f"\n[10] --keep: left {h[:12]}… stopped in {target}. Remove it with --cleanup.")
        return
    print("\n[10] Delete with files (torrents/delete, deleteFiles=true), then tidy up")
    box.delete([h], delete_files=True)
    box.wait_for(h, lambda r: r is None, timeout=30, on_poll=poll)
    removed = box.cleanup(extra_tags=[HELPER_TAG], categories=[tag])
    print(f"    removed tags {removed['tags'] or '-'}, categories {removed['categories'] or '-'}")
    left = box.torrents()
    print(f"    sandbox torrents left: {len(left)}")
    print("\nAll lifecycle steps passed." if not left else "\n!! Leftovers in the sandbox; run --cleanup.")


if __name__ == "__main__":
    main()
