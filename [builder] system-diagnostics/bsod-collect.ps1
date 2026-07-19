# bsod-collect.ps1
# AI Agent pattern: write to temp file, deploy with Start-Process -Verb RunAs -Wait, then read
# Output is UTF-8 so agent's read_file tool can consume it directly.
#
# Usage from terminal (Git Bash):
#   powershell -NoProfile -Command "Start-Process powershell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File C:\path\to\bsod-collect.ps1' -Verb RunAs -Wait"
# Then read:
#   cat /c/Users/<user>/AppData/Local/Temp/bsod-collect-output.txt

$outFile = "$env:TEMP\bsod-collect-output.txt"
"BSOD Diagnosis - $(Get-Date)" | Out-File $outFile -Encoding UTF8

"`n=== 1. Critical System Errors (Level 1+2, last 30d) ===" | Out-File $outFile -Append -Encoding UTF8
Get-WinEvent -FilterHashtable @{LogName='System'; Level=1,2; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 100 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, Id, LevelDisplayName, Message | Format-List | Out-File $outFile -Append -Encoding UTF8

"`n=== 2. WER Crash Buckets (Event 1001) ===" | Out-File $outFile -Append -Encoding UTF8
Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001} -MaxEvents 30 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, Message | Format-List | Out-File $outFile -Append -Encoding UTF8

"`n=== 3. Minidump Inventory ===" | Out-File $outFile -Append -Encoding UTF8
Get-ChildItem C:\Windows\Minidump\*.dmp -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object Name, LastWriteTime, Length | Format-Table -AutoSize | Out-File $outFile -Append -Encoding UTF8

"`n=== 4. CrashControl Registry ===" | Out-File $outFile -Append -Encoding UTF8
Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\CrashControl" -ErrorAction SilentlyContinue |
    Select-Object CrashDumpEnabled, MinidumpsCount, Overwrite, DumpFile, MinidumpDir, DumpFilters | Format-Table -AutoSize | Out-File $outFile -Append -Encoding UTF8

"`n=== 5. Dump Write Events (161/162, last 30d) ===" | Out-File $outFile -Append -Encoding UTF8
Get-WinEvent -FilterHashtable @{LogName='System'; Id=161,162; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 20 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, Id, Message | Format-List | Out-File $outFile -Append -Encoding UTF8

"`n=== 6. Hardware ===" | Out-File $outFile -Append -Encoding UTF8
Get-CimInstance Win32_ComputerSystem | Select-Object Model, Manufacturer, TotalPhysicalMemory | Format-Table -AutoSize | Out-File $outFile -Append -Encoding UTF8
Get-CimInstance Win32_BIOS | Select-Object Manufacturer, SMBIOSBIOSVersion | Format-Table -AutoSize | Out-File $outFile -Append -Encoding UTF8
Get-PhysicalDisk | Select-Object FriendlyName, MediaType, HealthStatus, OperationalStatus, Size | Format-Table -AutoSize | Out-File $outFile -Append -Encoding UTF8

"`n=== 7. VBS / Core Isolation ===" | Out-File $outFile -Append -Encoding UTF8
Get-CimInstance -Namespace root/Microsoft/Windows/DeviceGuard -ClassName Win32_DeviceGuard -ErrorAction SilentlyContinue |
    Select-Object VirtualizationBasedSecurityStatus, SecurityServicesRunning, RequiredSecurityProperties, SecurityFeaturesEnabled | Format-Table -AutoSize | Out-File $outFile -Append -Encoding UTF8

"`n=== 8. Driver Errors (Event 10317, last 30d) ===" | Out-File $outFile -Append -Encoding UTF8
Get-WinEvent -FilterHashtable @{LogName='System'; Id=10317} -MaxEvents 10 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, Message | Format-List | Out-File $outFile -Append -Encoding UTF8

"`n=== 9. Memory Integrity Keys ===" | Out-File $outFile -Append -Encoding UTF8
Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity" -Name Enabled -ErrorAction SilentlyContinue | Out-File $outFile -Append -Encoding UTF8
Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity" -Name ChangedInBootCycle -ErrorAction SilentlyContinue | Out-File $outFile -Append -Encoding UTF8
Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard" -Name RequireMicrosoftSignedBootChain -ErrorAction SilentlyContinue | Out-File $outFile -Append -Encoding UTF8

"`n=== 10. Uptime ===" | Out-File $outFile -Append -Encoding UTF8
$os = Get-CimInstance Win32_OperatingSystem
$uptime = (Get-Date) - $os.LastBootUpTime
"$($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m since $($os.LastBootUpTime)" | Out-File $outFile -Append -Encoding UTF8

"`n=== 11. Event 1001 Raw XML (latest) ===" | Out-File $outFile -Append -Encoding UTF8
$e = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001} -MaxEvents 1 -ErrorAction SilentlyContinue
if ($e) {
    $xml = [xml]$e.ToXml()
    $xml.Event.EventData.Data | Format-Table Name, '#text' -AutoSize | Out-File $outFile -Append -Encoding UTF8
} else {
    "No Event 1001 found." | Out-File $outFile -Append -Encoding UTF8
}

"`n=== DONE ===" | Out-File $outFile -Append -Encoding UTF8
