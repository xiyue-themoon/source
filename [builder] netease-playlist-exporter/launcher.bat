@echo off
rem ============================================
rem  NetEase Playlist Exporter launcher
rem  Double-click to run. Output .txt lands in
rem  the same folder as this bat/exe.
rem ============================================
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0playlist_exporter.exe"
