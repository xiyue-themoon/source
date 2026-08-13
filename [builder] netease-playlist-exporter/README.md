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

```
playlist_exporter.exe <url_or_uid> [-o output.txt]
playlist_exporter.exe                      # interactive prompt
```

Input forms:
- `https://music.163.com/m/playlist?id=6981767948&creatorId=5192244309`
- `https://music.163.com/playlist?id=6981767948`   (creator auto-resolved)
- bare uid digits, e.g. `5192244309`

Default output: `playlists_<uid>.txt` next to the exe (double-click safe).

## APIs used (all anonymous, no login)

| API | Purpose |
|:----|:--------|
| `/api/user/playlist?uid=X` | list all playlists of user |
| `/api/v6/playlist/detail` (POST) | trackIds of a playlist |
| `/api/v3/song/detail` (POST) | batch song title/artist, 200 ids/call |

## Build

```
hermes_python -m pip install pyinstaller
hermes_python -m PyInstaller --onefile --console --name playlist_exporter --clean playlist_exporter.py
# output: dist/playlist_exporter.exe
```

hermes_python = `C:\Users\ROG\miniconda3\envs\hermes\python.exe`

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

- 2026-08-13: uid 5192244309 → 39 owned playlists, 4433 tracks, exe run
  from %TEMP% produced identical output to the script.
