Write-Host "=============================================="
Write-Host "  SYSTEM HEALTH CHECK"
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "=============================================="
Write-Host ""

Write-Host "=== 1. SYSTEM UPTIME & MEMORY ==="
$os = Get-CimInstance Win32_OperatingSystem
$uptime = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$freeMB = [math]::Round($os.FreePhysicalMemory / 1KB, 1)
$pct = [math]::Round($os.FreePhysicalMemory / $os.TotalVisibleMemorySize * 100, 1)
Write-Host "  Uptime:     $uptime hours"
Write-Host "  RAM Total:  $totalGB GB"
Write-Host "  RAM Free:   $freeMB MB ($pct%)"
Write-Host ""

Write-Host "=== 2. DISK USAGE ==="
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    $d = $_.DeviceID
    $total = [math]::Round($_.Size / 1GB, 1)
    $free = [math]::Round($_.FreeSpace / 1GB, 1)
    $used = [math]::Round(($_.Size - $_.FreeSpace) / 1GB, 1)
    $pctx = [math]::Round($_.FreeSpace / $_.Size * 100, 1)
    Write-Host "  $d  Total: ${total}G  Used: ${used}G  Free: ${free}G ($pctx%)"
}
Write-Host ""

Write-Host "=== 3. GPU STATUS ==="
try {
    $gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA|RTX|4070" } | Select-Object -First 1
    if ($gpu) {
        Write-Host "  GPU: $($gpu.Name)"
        Write-Host "  Driver: $($gpu.DriverVersion)"
        Write-Host "  VRAM (WMI):  $([math]::Round($gpu.AdapterRAM / 1GB, 1)) GB"
        Write-Host '  NOTE: WMI often under-reports VRAM (e.g. reports 4GB for 8GB card)'
        Write-Host '  Use nvidia-smi for accurate VRAM'
    } else {
        Write-Host "  NVIDIA GPU not found via WMI, checking nvidia-smi..."
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null
    }
}
catch { Write-Host "  Could not query GPU" }
Write-Host ""

Write-Host "=== 4. NVIDIA-SMI (Temp, Power, Utilization) ==="
try {
    nvidia-smi --query-gpu=temperature.gpu,power.draw,utilization.gpu,utilization.memory --format=csv,noheader 2>$null
}
catch { Write-Host "  nvidia-smi not available" }
Write-Host ""

Write-Host "=== 5. TOP 10 PROCESSES BY MEMORY ==="
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 | ForEach-Object {
    Write-Host ("  {0,-35} {1,8} MB  CPU:{2,5}s" -f $_.ProcessName, [math]::Round($_.WorkingSet64/1MB,1), [math]::Round($_.TotalProcessorTime.TotalSeconds,1))
}
Write-Host ""

Write-Host "=== 6. CRITICAL SYSTEM EVENTS (Last 24h) ==="
$errs = Get-WinEvent -FilterHashtable @{LogName='System'; Level=1,2; StartTime=(Get-Date).AddHours(-24)} -MaxEvents 20 -ErrorAction SilentlyContinue
if ($errs) {
    $errs | ForEach-Object {
        Write-Host ("  [{0}] {1} - {2}" -f $_.TimeCreated.ToString("HH:mm"), $_.ProviderName, $_.Id)
    }
} else {
    Write-Host "  No critical system events in last 24h"
}
Write-Host ""

Write-Host "=== 7. APPLICATION EVENTS (Last 24h) ==="
$appErrs = Get-WinEvent -FilterHashtable @{LogName='Application'; Level=1,2; StartTime=(Get-Date).AddHours(-24)} -MaxEvents 20 -ErrorAction SilentlyContinue
if ($appErrs) {
    $appErrs | ForEach-Object {
        Write-Host ("  [{0}] {1} - {2}" -f $_.TimeCreated.ToString("HH:mm"), $_.ProviderName, $_.Id)
    }
} else {
    Write-Host "  No critical application events in last 24h"
}
Write-Host ""

Write-Host "=== 8. SERVICE STATUS (key services) ==="
$services = @("Tailscale", "Ollama", "WinDivert", "fastgithub")
foreach ($svc in $services) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s) {
        Write-Host ("  {0,-25} {1}" -f $svc, $s.Status)
    } else {
        Write-Host ("  {0,-25} NOT FOUND" -f $svc)
    }
}
Write-Host ""

Write-Host "=============================================="
Write-Host "  SYSTEM HEALTH CHECK COMPLETE"
Write-Host "=============================================="
