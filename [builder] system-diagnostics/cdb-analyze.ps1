<#
.SYNOPSIS
    Quick cdb dump analysis: copy latest minidump (elevated), run .bugcheck + k 20 + lm.
.DESCRIPTION
    Phase 3 deep analysis. Copies the specified minidump to a writable temp location
    (requires admin elevation for the copy), then runs cdb's quick commands WITHOUT
    symbol download. Outputs bugcheck code, 20-frame stack trace, loaded modules,
    and unloaded modules list.
.PARAMETER DumpName
    Name of the minidump file in C:\Windows\Minidump\ (e.g. '061126-11187-01.dmp').
    If omitted, analyzes the most recent dump.
.PARAMETER KeepCopy
    Switch: keep the elevated copy under C:\Users\$env:USERNAME\ after analysis.
    Default removes it.
.EXAMPLE
    .\cdb-analyze.ps1
    .\cdb-analyze.ps1 -DumpName '061126-11187-01.dmp'
    .\cdb-analyze.ps1 -KeepCopy
#>

param(
    [string]$DumpName = "",
    [switch]$KeepCopy
)

# ── Locate cdb ──
try {
    $loc = (Get-AppxPackage -Name Microsoft.WinDbg).InstallLocation
    $cdb = Join-Path $loc "amd64\cdb.exe"
    if (-not (Test-Path $cdb)) { throw "cdb.exe not found at $cdb" }
} catch {
    Write-Host "ERROR: WinDbg not installed. Install with:" -ForegroundColor Red
    Write-Host "  winget install Microsoft.WinDbg --accept-source-agreements"
    exit 1
}

# ── Find dump ──
$dumpDir = "C:\Windows\Minidump"
if ($DumpName) {
    $source = Join-Path $dumpDir $DumpName
} else {
    $source = Get-ChildItem "$dumpDir\*.dmp" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}

if (-not $source -or -not (Test-Path $source)) {
    Write-Host "ERROR: no minidump found" -ForegroundColor Red
    exit 1
}

Write-Host ("Source: " + $source) -ForegroundColor Cyan
Write-Host ("Size: " + ((Get-Item $source).Length / 1KB).ToString("F0") + " KB")

# ── Copy with admin ──
$dest = Join-Path $env:TEMP "crash-analyze.dmp"
Write-Host "Copying to $dest (elevated)..." -ForegroundColor DarkGray

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "cmd.exe"
$psi.Arguments = "/c copy /Y `"$source`" `"$dest`""
$psi.Verb = "runas"
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$p = [System.Diagnostics.Process]::Start($psi)
$p.WaitForExit()

if (-not (Test-Path $dest)) {
    Write-Host "ERROR: admin copy failed" -ForegroundColor Red
    exit 1
}

# ── Run cdb quick analysis (no symbols) ──
Write-Host ""
Write-Host "=== cdb Quick Analysis ===" -ForegroundColor Cyan
Write-Host "(no symbols — fast path)" -ForegroundColor DarkGray
Write-Host ""

$cdbArgs = @('-z', $dest, '-c', '.bugcheck; k 20; lm; q')
$result = & $cdb $cdbArgs 2>&1 | Out-String

# Extract just the key sections
$lines = $result -split "`n"

$inBugcheck = $false
$inStack = $false
$inModules = $false
$inUnloaded = $false
$section = "header"

foreach ($line in $lines) {
    # Detect section transitions
    if ($line -match 'Bugcheck code') {
        $section = "bugcheck"; Write-Host "`n── BugCheck ──" -ForegroundColor Yellow
        Write-Host $line
        continue
    }
    if ($section -eq "bugcheck" -and $line -match 'Arguments') {
        Write-Host $line; continue
    }
    if ($section -eq "bugcheck" -and $line -match 'Child-SP') {
        $section = "stack"; Write-Host "`n── Stack (top 20) ──" -ForegroundColor Yellow
        Write-Host $line
        continue
    }
    if ($section -eq "stack" -and $line -match 'start\s+end\s+module') {
        $section = "modules"; Write-Host "`n── Loaded Modules (third-party) ──" -ForegroundColor Yellow
        continue
    }
    if ($section -eq "stack" -or $section -eq "bugcheck") {
        Write-Host $line
        continue
    }
    if ($section -eq "modules") {
        if ($line -match 'Unloaded modules:') {
            $section = "unloaded"; Write-Host "`n── Unloaded Modules ──" -ForegroundColor Yellow
            continue
        }
        # Only show non-Microsoft modules
        if ($line -match 'fffff') {
            $parts = $line -split '\s+'
            if ($parts.Count -ge 4) {
                $mod = $parts[3]
                # Flag non-Microsoft paths
                $isMs = $mod -match '^nt$|^hal$|^Ntfs$|^FLTMGR$|^dxg' -or
                        $line -match 'system32|microsoft'
                if (-not $isMs) {
                    Write-Host ("  " + $line.Trim()) -ForegroundColor DarkGray
                } elseif ($mod -match 'ACE|uiomap|inpout|WinDivert|FrameView|nvpcf|AsIO|UnionFS|TbtBus') {
                    Write-Host ("  " + $line.Trim()) -ForegroundColor Red
                }
            }
        }
        continue
    }
    if ($section -eq "unloaded") {
        if ($line -match '^quit:') { break }
        Write-Host ("  " + $line.Trim())
    }
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan

# ── Cleanup ──
if (-not $KeepCopy -and (Test-Path $dest)) {
    Remove-Item $dest -Force
    Write-Host "Temp dump deleted." -ForegroundColor DarkGray
}
