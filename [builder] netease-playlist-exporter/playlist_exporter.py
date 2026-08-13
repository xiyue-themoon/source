#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NetEase Music playlist exporter - one-click fetch all owned playlists of a user.
Usage:
    playlist_exporter.exe <url_or_uid> [-o output.txt]
    playlist_exporter.exe            (interactive prompt)
Output: UTF-8 text file, each playlist section + "title - artist" lines.
Pure ASCII program messages (GBK console safe). Chinese only in data.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# Force UTF-8 console output (works on Windows Terminal / chcp 65001;
# on legacy GBK consoles, Chinese chars may garble but files stay correct)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Default output dir: next to the exe (or script), so double-click works
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
BASE = "https://music.163.com/api"


def http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://music.163.com/", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA, "Referer": "https://music.163.com/",
        "Accept": "*/*", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_input(arg):
    """Return (playlist_id_or_None, creator_uid_or_None)."""
    arg = arg.strip()
    m = re.search(r"[?&]id=(\d+)", arg)
    pid = m.group(1) if m else None
    m = re.search(r"[?&]creatorId=(\d+)", arg) or re.search(r"[?&]userid=(\d+)", arg)
    uid = m.group(1) if m else None
    if arg.isdigit():
        if len(arg) >= 8:
            return None, arg
        return arg, None
    if not pid and not uid:
        return None, None
    return pid, uid


def resolve_creator(pid):
    d = http_post(f"{BASE}/v6/playlist/detail", {"id": pid, "n": 1, "s": 0})
    if d.get("code") != 200:
        raise RuntimeError("playlist detail API failed")
    pl = d.get("playlist") or {}
    return pl.get("userId"), pl.get("name", "?")


def get_user_playlists(uid):
    d = http_get(f"{BASE}/user/playlist?uid={uid}&limit=100&offset=0")
    if d.get("code") != 200:
        raise RuntimeError("user playlist API failed")
    return [p for p in (d.get("playlist") or [])
            if p.get("creator", {}).get("userId") == int(uid)]


def get_playlist_meta(pid):
    d = http_post(f"{BASE}/v6/playlist/detail", {"id": pid, "n": 1, "s": 0})
    if d.get("code") != 200:
        return None, None
    pl = d.get("playlist") or {}
    tids = [t["id"] for t in (pl.get("trackIds") or []) if isinstance(t, dict)]
    return pl.get("name", "?"), tids


def get_song_details(ids):
    out = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i+200]
        c = json.dumps([{"id": tid} for tid in chunk], ensure_ascii=False)
        for attempt in range(3):
            try:
                d = http_post(f"{BASE}/v3/song/detail", {"c": c})
                for s in d.get("songs") or []:
                    ars = " / ".join(a.get("name", "") for a in s.get("ar", []))
                    out[s.get("id")] = (s.get("name", "?"), ars)
                break
            except Exception:
                if attempt == 2:
                    print(f"  WARN: chunk {i} failed after 3 tries, skipping")
                else:
                    time.sleep(2)
        time.sleep(0.2)
    return out


def run(uid, out_path):
    print(f"Fetching playlists of uid {uid} ...")
    playlists = get_user_playlists(uid)
    if not playlists:
        print("No owned playlists found for this uid.")
        return 1
    playlists.sort(key=lambda p: p.get("createTime", 0))
    print(f"Found {len(playlists)} owned playlists.")

    lines, total, failed = [], 0, []
    for p in playlists:
        pid = p["id"]
        name, tids = get_playlist_meta(pid)
        if tids is None:
            failed.append(pid)
            continue
        print(f"  [{pid}] {name} ({len(tids)} tracks)")
        details = get_song_details(tids)
        lines.append(f"===== {name} [{pid}] ({len(tids)} tracks) =====")
        for tid in tids:
            title, artist = details.get(tid, ("?", "?"))
            lines.append(f"{title} - {artist}")
            total += 1
        lines.append("")
        time.sleep(0.2)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"DONE. Playlists: {len(playlists)}, Tracks: {total}")
    if failed:
        print(f"FAILED playlist ids: {failed}")
    print(f"Saved: {out_path}")
    return 0


def main():
    args = sys.argv[1:]
    out_path = None
    pos = []
    i = 0
    while i < len(args):
        if args[i] in ("-o", "--output") and i + 1 < len(args):
            out_path = args[i + 1]
            i += 2
        else:
            pos.append(args[i])
            i += 1

    arg = pos[0] if pos else ""
    if not arg:
        try:
            arg = input("Paste NetEase Music playlist share URL or uid: ").strip()
        except EOFError:
            print("No input. Usage: playlist_exporter.exe <url_or_uid> [-o output.txt]")
            return 1

    pid, uid = parse_input(arg)
    if not uid and pid:
        print(f"Resolving creator from playlist {pid} ...")
        uid, pname = resolve_creator(pid)
        print(f"Creator uid: {uid} (playlist: {pname})")
    if not uid:
        print("Cannot determine user uid from input.")
        print("Expected: share URL like https://music.163.com/m/playlist?id=XXX&creatorId=YYY")
        print("          or a bare user uid (digits)")
        return 1

    if not out_path:
        out_path = os.path.join(APP_DIR, f"playlists_{uid}.txt")

    try:
        return run(uid, out_path)
    except Exception as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
