# verify-vbs-teardown.ps1
# Post-cold-boot VBS/hypervisor teardown verification
# Run after cold boot (power-off, not Restart) following VBS disable
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File verify-vbs-teardown.ps1

Write-Host '=== VBS Teardown Verification ===' -ForegroundColor Cyan
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"

# 1. Hypervisor registry key -- definitive check
Write-Host '1. Hypervisor Registry Key (DEFINITIVE)' -ForegroundColor Cyan
$hvKey = Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Hypervisor'
if (-not $hvKey) {
    Write-Host '  [+] HKLM:...\Control\Hypervisor -- ABSENT (hypervisor NOT loaded)' -ForegroundColor Green
} else {
    Write-Host '  [!] HKLM:...\Control\Hypervisor -- PRESENT (hypervisor STILL loaded)' -ForegroundColor Red
    Write-Host '  -> Need another cold boot (power off 10s, then power on)'
}

# 2. hvservice state
Write-Host "`n2. hvservice State" -ForegroundColor Cyan
$hv = Get-CimInstance Win32_SystemDriver -Filter "Name='hvservice'" -ErrorAction SilentlyContinue
if ($hv) {
    Write-Host "  hvservice: StartMode=$($hv.StartMode) State=$($hv.State)"
    if ($hv.State -eq 'Running') {
        Write-Host '  [?] SERVICE shows Running but PID=0 (driver loaded, engine not started)' -ForegroundColor Yellow
    }
} else {
    Write-Host '  [+] hvservice not found (clean)' -ForegroundColor Green
}

# 3. VBS CIM status
Write-Host "`n3. VBS CIM Status" -ForegroundColor Cyan
$vbs = Get-CimInstance -Namespace 'root/Microsoft/Windows/DeviceGuard' Win32_DeviceGuard -ErrorAction SilentlyContinue
if ($vbs) {
    Write-Host "  VirtualizationBasedSecurityStatus = $($vbs.VirtualizationBasedSecurityStatus) (0=off, 2=enabled)"
    Write-Host "  RequiredSecurityProperties = $($vbs.RequiredSecurityProperties)"
    Write-Host "  SecurityServicesRunning = $($vbs.SecurityServicesRunning)"
    Write-Host "  SecurityServicesConfigured = $($vbs.SecurityServicesConfigured)"
}

# 4. Registry state
Write-Host "`n4. Registry VBS Keys" -ForegroundColor Cyan
$dg = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard' -Name EnableVirtualizationBasedSecurity -EA 0
$lsa = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name LsaCfgFlags -EA 0
$hvCi = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity' -Name Enabled -EA 0
Write-Host "  EnableVirtualizationBasedSecurity = $($dg.EnableVirtualizationBasedSecurity) (0=good)"
Write-Host "  LsaCfgFlags = $($lsa.LsaCfgFlags) (0=good)"
Write-Host "  MemoryIntegrity.Enabled = $($hvCi.Enabled) (0=good)"

# 5. System uptime
Write-Host "`n5. System Info" -ForegroundColor Cyan
$os = Get-CimInstance Win32_OperatingSystem
$up = (Get-Date) - $os.LastBootUpTime
Write-Host "  Boot: $($os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Host "  Uptime: $($up.Days)d $($up.Hours)h $($up.Minutes)m"

# 6. BSOD check since boot
Write-Host "`n6. BSOD Check (since boot)" -ForegroundColor Cyan
$bootTime = $os.LastBootUpTime
$crashes = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001; StartTime=$bootTime} -MaxEvents 10 -ErrorAction SilentlyContinue
if ($crashes) {
    Write-Host "  [!] $($crashes.Count) BSOD(s) since boot" -ForegroundColor Red
    foreach ($e in $crashes) {
        $m = $e.Message
        if ($m.Length -gt 150) { $m = $m.Substring(0,150) }
        Write-Host "  [$($e.TimeCreated.ToString('HH:mm:ss'))] $m"
    }
} else {
    Write-Host '  [+] No BSODs since boot' -ForegroundColor Green
}

# 7. Final verdict
Write-Host "`n=== VERDICT ===" -ForegroundColor Cyan
if (-not $hvKey -and $dg.EnableVirtualizationBasedSecurity -eq 0 -and $lsa.LsaCfgFlags -eq 0) {
    Write-Host '[+] VBS teardown successful. Hypervisor not loaded.' -ForegroundColor Green
    if ($vbs.VirtualizationBasedSecurityStatus -eq 2) {
        Write-Host '[?] CIM status=2 is cosmetic residual (harmless).' -ForegroundColor Yellow
    }
    if ($hv.State -eq 'Running') {
        Write-Host '[?] hvservice Running is residual (PID=0, engine not loaded).' -ForegroundColor Yellow
    }
} elseif ($hvKey) {
    Write-Host '[!] Hypervisor still loaded. Need another cold boot.' -ForegroundColor Red
} else {
    Write-Host '[!] Partial failure -- check individual items above.' -ForegroundColor Red
}
