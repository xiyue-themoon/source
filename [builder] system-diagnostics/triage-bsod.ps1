<#
.SYNOPSIS
    Phase 1 BSOD triage: list minidumps, extract BugCheck codes + WER buckets from System event log.
.DESCRIPTION
    Run this first when the user reports a BSOD. Outputs a structured timeline of
    recent crashes with bugcheck codes, dump file paths, and drivers to investigate.
    No admin required for the event log queries. Minidump listing does not require admin.
.PARAMETER Days
    Number of days to look back (default: 7).
.PARAMETER MaxEvents
    Max BSOD records to return (default: 20).
.EXAMPLE
    .\triage-bsod.ps1
    .\triage-bsod.ps1 -Days 14 -MaxEvents 50
#>

param(
    [int]$Days = 7,
    [int]$MaxEvents = 20
)

$cutoff = (Get-Date).AddDays(-$Days)

# ── Minidump list ──
Write-Host "=== Minidump Files (last $Days days) ===" -ForegroundColor Cyan
$dumps = Get-ChildItem C:\Windows\Minidump\*.dmp -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
if ($dumps) {
    $dumps | Select-Object Name,
        @{N='Size(KB)';E={[int]($_.Length/1024)}},
        @{N='CrashTime';E={$_.LastWriteTime}} |
        Format-Table -AutoSize
} else {
    Write-Host "  (no minidumps found)" -ForegroundColor Yellow
}

# ── WinDbg path (if installed) ──
try {
    $loc = (Get-AppxPackage -Name Microsoft.WinDbg).InstallLocation
    $cdb = Join-Path $loc "amd64\cdb.exe"
    Write-Host ("WinDbg cdb: " + $cdb) -ForegroundColor DarkGray
} catch {
    Write-Host "WinDbg: NOT INSTALLED (cdb unavailable)" -ForegroundColor DarkGray
}

# ── Event ID 1001 (BugCheck) ──
Write-Host ""
Write-Host "=== Crash Timeline (Event ID 1001, last $Days days) ===" -ForegroundColor Cyan
$events = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001; StartTime=$cutoff} `
    -MaxEvents $MaxEvents -ErrorAction SilentlyContinue

if (-not $events) {
    Write-Host "  (no BSOD records found)" -ForegroundColor Green
    return
}

$events | ForEach-Object {
    $msg = $_.Message
    Write-Host ("--- " + $_.TimeCreated + " ---") -ForegroundColor Yellow

    # BugCheck code
    if ($msg -match '(0x[0-9a-fA-F]{8})') {
        $bc = $Matches[1]
        $name = switch -regex ($bc) {
            '0x0000003b' { 'SYSTEM_SERVICE_EXCEPTION' }
            '0x0000001e' { 'KMODE_EXCEPTION_NOT_HANDLED' }
            '0x0000007f' { 'UNEXPECTED_KERNEL_MODE_TRAP' }
            '0x00000050' { 'PAGE_FAULT_IN_NONPAGED_AREA' }
            '0x00000001' { 'APC_INDEX_MISMATCH' }
            '0x0000000a' { 'IRQL_NOT_LESS_OR_EQUAL' }
            '0x000000d1' { 'DRIVER_IRQL_NOT_LESS_OR_EQUAL' }
            '0x0000001a' { 'MEMORY_MANAGEMENT' }
            default      { ('0x' + $bc.Substring(8)) }
        }
        Write-Host ("  BugCheck: $bc ($name)") -ForegroundColor Magenta
    }

    # Dump file path
    if ($msg -match '(C:\\Windows\\Minidump\\[^\s]+)') {
        Write-Host ("  Dump: " + $Matches[1])
    }

    # WER bucket
    if ($msg -match 'Bucket\s*:\s*([\w\.!_]+)') {
        Write-Host ("  Bucket: " + $Matches[1]) -ForegroundColor Cyan
    }
    if ($msg -match 'failure bucket\s*:\s*([\w\.!_]+)') {
        Write-Host ("  FailureBucket: " + $Matches[1]) -ForegroundColor Cyan
    }

    Write-Host ""
}

# ── Summary stats ──
$codes = @{}
$events | ForEach-Object {
    if ($_.Message -match '(0x[0-9a-fA-F]{8})') {
        $c = $Matches[1]
        if ($codes.ContainsKey($c)) { $codes[$c] += 1 } else { $codes[$c] = 1 }
    }
}
Write-Host "=== Crash Summary ===" -ForegroundColor Cyan
$codes.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object {
    Write-Host ("  " + $_.Key + " × " + $_.Value)
}
Write-Host ("  Total: " + $events.Count + " crashes")
