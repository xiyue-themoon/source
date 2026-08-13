# [builder] netease-playlist-exporter

NetEase Music (music.163.com) playlist exporter — one-click dump ALL owned
playlists of a user into a UTF-8 text file (title - artist per line).

## What it does

Given a playlist share URL or a user uid, resolves the account (creator),
enumerates every playlist the account OWNED (not subscribed), fetches all
track ids, then batch-resolves song title + artists, writes a UTF-8 text
file with one `===== playlist name [id] (N tracks) =====` section per
playlist.

## Usage

Double-click `launcher.bat` (or `playlist_exporter.exe`) -> paste share URL
-> Enter -> output txt appears next to the exe.

CLI forms:
- `playlist_exporter.exe <url_or_uid> [-o output.txt]`
- `playlist_exporter.exe`                      # interactive prompt

Input forms:
- `https://music.163.com/m/playlist?id=123456&creatorId=789012` (example)
- `https://music.163.com/playlist?id=123456`   (creator auto-resolved)
- bare uid digits, e.g. `789012`

Default output: `playlists_<uid>.txt` next to the exe (double-click safe).

## Launcher (shell)

`launcher.bat` = `chcp 65001` (UTF-8 console, Chinese UI renders) +
`cd /d %~dp0` (output lands in the exe folder regardless of cwd) + run exe.
exe itself pauses on exit ("Press Enter") so the window doesn't vanish.
Source stays pure ASCII: Chinese UI strings are `\uXXXX` escapes in the
source, rendered at runtime after the console switches to 65001.

## APIs used (all anonymous, no login)

| API | Purpose |
|:----|:--------|
| `/api/user/playlist?uid=X` | list all playlists of user |
| `/api/v6/playlist/detail` (POST) | trackIds of a playlist |
| `/api/v3/song/detail` (POST) | batch song title/artist, 200 ids/call |

## Build

```
hermes_python -m pip install pyinstaller
hermes_python -m PyInstaller --onefile --console --name playlist_exporter \
  --add-binary "C:/Windows/System32/VCRUNTIME140_1.dll;." --clean playlist_exporter.py
# output: dist/playlist_exporter.exe
```

hermes_python = `C:\Users\ROG\miniconda3\envs\hermes\python.exe`

**Why the --add-binary is REQUIRED**: python312.dll links VCRUNTIME140_1.dll,
but PyInstaller 6.22's hooks only bundle VCRUNTIME140.dll. On a clean foreign
PC without VC++ Redistributable installed, the exe dies with
"VCRUNTIME140_1.dll not found". Bundling it explicitly fixes that.

## Portability (verified 2026-08-13)

- Architecture: x64 (Machine 0x8664). Requires 64-bit Windows 10/11.
- Self-contained: 60 bundled DLLs/pyds incl. python312.dll, VCRUNTIME140.dll,
  VCRUNTIME140_1.dll, ucrtbase.dll, OpenSSL, zlib. Bootloader imports only
  USER32/KERNEL32/ADVAPI32 (present on every Win10/11).
- Verified by running the exe from a neutral temp dir with a stripped env
  (PATH=System32 only, no conda, no user PATH): full export works, output
  lands next to the exe. No dependency on the build machine.
- SmartScreen caveat: unsigned exe may show "Windows protected your PC"
  on first run (More info -> Run anyway). Normal for unsigned tools.
- Antivirus caveat: PyInstaller onefile exes occasionally trigger false
  positives in aggressive AV (360 etc.). Source is on GitHub for review.

## Pitfalls (learned)

1. **GET with `?c=[{...}]` → HTTP 414** — the song-detail JSON array in the
   query string exceeds URL limits at ~200 ids. MUST POST the `c` param.
2. **trackIds are dicts** — extract `t["id"]`, don't pass the dict into
   `song/detail`.
3. **`/api/user/playlist` returns owned + subscribed mixed** — filter
   `creator.userId == uid` to get owned only (subscribed playlists have a
   different creator).
4. **trackCount may differ from trackIds length** — deleted/unavailable
   tracks vanish from trackIds; the file reflects reality.
5. **Console GBK** — force `sys.stdout.reconfigure(encoding="utf-8")`;
   legacy cmd.exe still garbles Chinese progress lines but the output file
   is always correct UTF-8.
6. **Default output dir = exe dir** (`sys.frozen` check) so double-click
   from Explorer works regardless of cwd.

## Verification

- 2026-08-13: test account (uid hidden) → 39 owned playlists, 4433 tracks, exe run
  from %TEMP% produced identical output to the script.
