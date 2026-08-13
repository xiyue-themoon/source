#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NetEase Music playlist exporter - one-click fetch all owned playlists of a user.
Usage:
    playlist_exporter.exe <url_or_uid> [-o output.txt]
    playlist_exporter.exe            (interactive prompt, double-click friendly)
Output: UTF-8 text file, each playlist section + "title - artist" lines.
Source is pure ASCII; Chinese UI strings are \\uXXXX escapes rendered at runtime.
"""
import ctypes
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# --- Console codepage adaptation -------------------------------------------
# On double-click (cmd.exe, GBK cp936), switch console to UTF-8 so Chinese UI
# renders correctly. On Windows Terminal / chcp 65001 already, no-op.
def _console_codepage():
    try:
        return ctypes.windll.kernel32.GetConsoleOutputCP()
    except Exception:
        return 65001

def _ensure_utf8_console():
    try:
        if _console_codepage() != 65001:
            os.system("chcp 65001 >nul")
    except Exception:
        pass

_ensure_utf8_console()
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

# --- UI strings (Chinese, stored as unicode escapes -> pure ASCII source) --
U = {
    "banner": "==== NetEase Playlist Exporter ====",
    "prompt": "\u8bf7\u7c98\u8d34\u7f51\u6613\u4e91\u6b4c\u5355\u5206\u4eab\u94fe\u63a5\uff08\u6216\u8f93\u5165\u7528\u6237UID\uff09\uff0c\u7136\u540e\u6309\u56de\u8f66\uff1a",
    "prompt_noinput": "\u672a\u68c0\u6d4b\u5230\u8f93\u5165\uff0c\u7a0b\u5e8f\u9000\u51fa\u3002",
    "resolve": "\u6b63\u5728\u89e3\u6790\u6b4c\u5355\u521b\u5efa\u8005...",
    "resolve_ok": "\u5df2\u8bc6\u522b\u8d26\u53f7 UID\uff1a{uid}\uff08\u6b4c\u5355\uff1a{name}\uff09",
    "found": "\u627e\u5230 {n} \u4e2a\u81ea\u5efa\u6b4c\u5355\uff0c\u5f00\u59cb\u62c9\u53d6...",
    "fetch_playlist": "  [{pid}] {name}\uff08{n} \u9996\uff09",
    "done": "\u5168\u90e8\u5b8c\u6210\uff01\u5171\u5bfc\u51fa {n} \u9996\u6b4c\u3002",
    "saved": "\u6587\u4ef6\u5df2\u4fdd\u5b58\u5230\uff1a{path}",
    "failed": "\u5931\u8d25\u6b4c\u5355 ID\uff1a{ids}",
    "error": "\u9519\u8bef\uff1a{msg}",
    "exit": "\u6309\u56de\u8f66\u952e\u9000\u51fa...",
    "help_url": "\u793a\u4f8b\uff1ahttps://music.163.com/m/playlist?id=123&creatorId=456",
}


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
    print(U["found"].format(n=len(playlists)))

    lines, total, failed = [], 0, []
    for p in playlists:
        pid = p["id"]
        name, tids = get_playlist_meta(pid)
        if tids is None:
            failed.append(pid)
            continue
        print(U["fetch_playlist"].format(pid=pid, name=name, n=len(tids)))
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
    print(U["done"].format(n=total))
    if failed:
        print(U["failed"].format(ids=", ".join(map(str, failed))))
    print(U["saved"].format(path=out_path))
    return 0


def _pause():
    """Wait for Enter; tolerate EOF (piped/redirected input)."""
    try:
        input(U["exit"])
    except EOFError:
        pass


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

    print(U["banner"])
    arg = pos[0] if pos else ""
    if not arg:
        try:
            arg = input(U["prompt"]).strip()
        except EOFError:
            arg = ""
        if not arg:
            print(U["prompt_noinput"])
            print(U["help_url"])
            _pause()
            return 1

    pid, uid = parse_input(arg)
    if not uid and pid:
        print(U["resolve"])
        uid, pname = resolve_creator(pid)
        print(U["resolve_ok"].format(uid=uid, name=pname))
    if not uid:
        print(U["error"].format(msg="Cannot determine user uid from input."))
        print(U["help_url"])
        _pause()
        return 1

    if not out_path:
        out_path = os.path.join(APP_DIR, f"playlists_{uid}.txt")

    try:
        rc = run(uid, out_path)
    except Exception as e:
        print(U["error"].format(msg=e))
        rc = 1

    _pause()
    return rc


if __name__ == "__main__":
    sys.exit(main())
