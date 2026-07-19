<#
.SYNOPSIS
  Post-reboot BSOD health check — verify a fix worked after reboot.
  Designed to be ASCII-only so it runs without UTF-8 BOM encoding.
.DESCRIPTION
  Checks: system uptime, new BugCheck events (ID 1001) since last boot,
  unexpected shutdowns (ID 41), crash summary, GPU status.
  Outputs a compact PASS/FAIL line at the end.
.PARAMETER LogName
  Optional: search file to collect Event 1001/41 output (no elevation needed).
  Default: none (reads live events via Get-WinEvent).
.PARAMETER MinDumpPath
  Optional: path to minidump directory. Default: C:\Windows\Minidump.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File post-reboot-check.ps1
#>

param(
    [string]$MinDumpPath = "C:\Windows\Minidump"
)

$bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$uptime = (Get-Date) - $bootTime

Write-Host "=== POST-REBOOT HEALTH CHECK ==="
Write-Host "Last boot: $($bootTime.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Host "Uptime: $([Math]::Floor($uptime.TotalHours))h $($uptime.Minutes)m"
Write-Host ""

# 1. New BugCheck events since boot
Write-Host "--- BugCheck Events (ID 1001) ---"
$newBugchecks = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001; StartTime=$bootTime} -MaxEvents 20 -ErrorAction SilentlyContinue
if ($newBugchecks.Count -eq 0) {
    Write-Host "  None since reboot" -ForegroundColor Green
} else {
    $newBugchecks | ForEach-Object {
        $t = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
        if ($_.Message -match '0x[0-9a-fA-F]{8}') { $c = $matches[0] } else { $c = "unknown" }
        Write-Host "  [$t] BugCheck $c" -ForegroundColor Red
    }
}
Write-Host ""

# 2. New unexpected shutdowns since boot
Write-Host "--- Unexpected Shutdowns (ID 41) ---"
$newPower = Get-WinEvent -FilterHashtable @{LogName='System'; Id=41; StartTime=$bootTime} -MaxEvents 10 -ErrorAction SilentlyContinue
if ($newPower.Count -eq 0) {
    Write-Host "  None since reboot" -ForegroundColor Green
} else {
    Write-Host "  Count: $($newPower.Count)" -ForegroundColor Yellow
}
Write-Host ""

# 3. Crash summary (last 3 days)
Write-Host "--- Crash Summary (last 3 days) ---"
$cutoff = (Get-Date).AddDays(-3)
$all1001 = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001; StartTime=$cutoff} -MaxEvents 100 -ErrorAction SilentlyContinue
if ($all1001.Count -eq 0) {
    Write-Host "  No crashes in last 3 days" -ForegroundColor Green
} else {
    Write-Host "  Total crashes: $($all1001.Count)"
    $codes = @{}
    $all1001 | ForEach-Object {
        if ($_.Message -match '0x[0-9a-fA-F]{8}') {
            $code = $matches[0]
            if ($codes.ContainsKey($code)) { $codes[$code] += 1 } else { $codes[$code] = 1 }
        }
    }
    $codes.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object {
        Write-Host "    $($_.Key): $($_.Value) time(s)"
    }
}
Write-Host ""

# 4. Minidump file count
Write-Host "--- Minidump Files ---"
$dumps = Get-ChildItem "$MinDumpPath\*.dmp" -ErrorAction SilentlyContinue
if ($dumps.Count -eq 0) {
    Write-Host "  No dump files" -ForegroundColor Yellow
} else {
    $dumps | Sort-Object LastWriteTime -Descending | Select-Object Name, LastWriteTime, Length | Format-Table -AutoSize
}
Write-Host ""

# 5. GPU status (fallback to WMI if nvidia-smi not in PATH)
Write-Host "--- GPU Status ---"
$gpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*NVIDIA*" }
if ($gpu) {
    Write-Host "  $($gpu.Name)`n  Status: $($gpu.Status)"
} else {
    Write-Host "  No NVIDIA GPU found via WMI (check drivers)"
}
Write-Host ""

# 6. PASS/FAIL
Write-Host "=== RESULT ===" -ForegroundColor Cyan
if ($newBugchecks.Count -eq 0 -and $newPower.Count -eq 0) {
    Write-Host "PASS: zero new crashes, zero unexpected shutdowns since reboot" -ForegroundColor Green
    exit 0
} else {
    Write-Host "FAIL: new crashes or unexpected shutdowns detected since reboot" -ForegroundColor Red
    exit 1
}
