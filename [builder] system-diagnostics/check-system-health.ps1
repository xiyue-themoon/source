# System Health Check — Post-BSOD verification script
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File check-system-health.ps1
# Checks: minidumps, driver state, ACE traces, uptime, recent BugCheck events

Write-Host "=== MINIDUMPS (last 5) ==="
Get-ChildItem C:\Windows\Minidump\*.dmp -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name, LastWriteTime, @{N='SizeKB';E={[math]::Round($_.Length/1KB,1)}}

Write-Host ""
Write-Host "=== DRIVER STATUS ==="
$drivers = @("uiomap", "ACE-BOOT", "ACE-BASE", "ACE-GAME", "inpoutx64", "EasyAntiCheat", "BEDaisy")
foreach ($d in $drivers) {
    Write-Host "--- $d ---"
    sc query $d 2>&1
}

Write-Host ""
Write-Host "=== ACE FILES CHECK ==="
if (Test-Path "C:\Program Files\AntiCheatExpert") { Write-Host "WARNING: ACE dir EXISTS at C:\Program Files\AntiCheatExpert\" } else { Write-Host "ACE Program Files dir: CLEAN" }
$aceDrivers = Get-ChildItem C:\Windows\System32\drivers\ACE-* -ErrorAction SilentlyContinue
if ($aceDrivers) { Write-Host "WARNING: ACE drivers found in System32:"; $aceDrivers | Select-Object Name } else { Write-Host "ACE drivers in System32: CLEAN" }

Write-Host ""
Write-Host "=== SYSTEM UPTIME ==="
$os = Get-CimInstance Win32_OperatingSystem
$uptime = (Get-Date) - $os.LastBootUpTime
Write-Host "Last boot: $($os.LastBootUpTime)"
Write-Host "Uptime: $([math]::Round($uptime.TotalHours,1)) hours"

Write-Host ""
Write-Host "=== RECENT CRASHES (BugCheck 1001, last 3) ==="
Get-WinEvent -LogName System -MaxEvents 500 -ErrorAction SilentlyContinue | Where-Object { $_.Id -eq 1001 } | Select-Object -First 3 TimeCreated, @{N='BugCheck';E={$_.Properties[0].Value}} | Format-List

Write-Host ""
Write-Host "=== KERNEL-POWER 41 (last 1) ==="
Get-WinEvent -LogName System -MaxEvents 500 -ErrorAction SilentlyContinue | Where-Object { $_.Id -eq 41 } | Select-Object -First 1 TimeCreated, Message | Format-List
