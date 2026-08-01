<#
.SYNOPSIS
  Morning health check — 10-second glance at system state.
  PURE ASCII — runs on PS5.1 without BOM issues on any locale.
.DESCRIPTION
  Checks: OS uptime/RAM, GPU, disk, network, proxy, errors, env, key processes.
.NOTES
  Author: Hermes Builder
  Run: powershell -NoProfile -ExecutionPolicy Bypass -File health_check.ps1
#>

Write-Host "=== System Health Check ===" -ForegroundColor Cyan
Write-Host ""

# --- System Info ---
Write-Host "--- System ---"
$os = Get-CimInstance Win32_OperatingSystem
$boot = $os.LastBootUpTime
$up = (Get-Date) - $boot
Write-Host ("  Boot: " + $boot.ToString("yyyy-MM-dd HH:mm:ss"))
Write-Host ("  Up: " + $up.Days + "d " + $up.Hours + "h " + $up.Minutes + "m")
$uM = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory)/1MB, 1)
$tM = [math]::Round($os.TotalVisibleMemorySize/1MB, 1)
Write-Host ("  RAM: " + $uM + "/" + $tM + "GB used")

# --- GPU ---
Write-Host ""
Write-Host "--- GPU ---"
$nvidia = & "nvidia-smi" --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>$null
if ($nvidia) { Write-Host ("  " + $nvidia) } else { Write-Host "  nvidia-smi: not available" }

# --- Disks ---
Write-Host ""
Write-Host "--- Disks ---"
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -match "^[A-Z]:" } | ForEach-Object {
    $pct = [math]::Round(($_.Free/($_.Used+$_.Free)*100), 1)
    Write-Host ("  " + $_.Root + " " + [math]::Round($_.Used/1GB, 1) + "GB used / " + [math]::Round($_.Free/1GB, 1) + "GB free (" + $pct + "% free)")
}

# --- Network ---
Write-Host ""
Write-Host "--- Network ---"
$ping8 = Test-Connection 8.8.8.8 -Count 1 -Quiet -EA 0
$pingGH = Test-Connection github.com -Count 1 -Quiet -EA 0
$pingTC = Test-Connection 43.139.75.69 -Count 1 -Quiet -EA 0
if ($ping8) { Write-Host "  8.8.8.8: OK" } else { Write-Host "  8.8.8.8: FAIL" }
if ($pingGH) { Write-Host "  GitHub: OK" } else { Write-Host "  GitHub: FAIL" }
if ($pingTC) { Write-Host "  TencentCloud: OK" } else { Write-Host "  TencentCloud: FAIL" }

# --- Proxy ---
Write-Host ""
Write-Host "--- Proxy ---"
$px = Get-Process -Name "Clash Verge","v2ray","trojan","qv2ray","clash-verge" -EA 0
if ($px) {
    $names = ($px | Select-Object -ExpandProperty ProcessName | Sort-Object -Unique) -join ", "
    Write-Host ("  Running: " + $names)
} else {
    Write-Host "  Not running"
}

# --- System Errors (24h) ---
Write-Host ""
Write-Host "--- System Errors (24h) ---"
$errs = Get-WinEvent -LogName System -MaxEvents 100 -EA 0 | Where-Object { $_.LevelDisplayName -eq "Error" -and $_.TimeCreated -gt (Get-Date).AddHours(-24) }
if ($errs) {
    $errs | Group-Object ProviderName | Sort-Object Count -Desc | Select-Object -First 5 | ForEach-Object {
        Write-Host ("  [" + $_.Count + "x] " + $_.Name)
    }
} else {
    Write-Host "  None"
}

# --- Environment ---
Write-Host ""
Write-Host "--- Environment ---"
$py = python --version 2>&1
$pip = pip --version 2>&1
Write-Host ("  Python: " + $py)
Write-Host ("  pip: " + ($pip -split " ")[0..3] -join " ")
try { $uv = uv --version 2>&1; Write-Host ("  uv: " + $uv) } catch { Write-Host "  uv: not found" }

# --- Key Processes ---
Write-Host ""
Write-Host "--- Key Processes ---"
$watch = @("ollama", "sunshine", "hermes")
foreach ($n in $watch) {
    $proc = Get-Process -Name $n -EA 0
    if ($proc) {
        $mb = [math]::Round($proc.WorkingSet64/1MB, 1)
        Write-Host ("  " + $n + ": running (PID " + $proc.Id + ", " + $mb + "MB)")
    } else {
        Write-Host ("  " + $n + ": not running")
    }
}
