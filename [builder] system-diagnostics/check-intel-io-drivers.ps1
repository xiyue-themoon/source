<#
.SYNOPSIS
  Check Intel IO / Chipset / Serial IO driver versions.
  Used to identify whether iaLPSS2_*.sys (Intel Serial IO) needs updating
  as part of BSOD root-cause analysis (0xd1 / IRQL_NOT_LESS_OR_EQUAL).

.DESCRIPTION
  Lists all Intel-signed drivers, then filters to IO/Chipset/SerialIO
  specific ones. Shows DeviceName, DriverVersion, DriverDate for quick
  comparison against latest OEM or Intel reference driver.

  Typical BSOD culprit: iaLPSS2_I2C_ADL.sys (I2C host controller for Alder Lake).
  If its version lags behind the Intel/ASUS latest published driver, update it
  as a parallel fix alongside VBS disable (see SKILL.md Phase 3 crash taxonomy
  for the Intel LPSS/Serial IO row).

.OUTPUT
  Sections:
    1. All Intel drivers (full table)
    2. Intel IO/Chipset/SerialIO filtered subset
    3. Summary counts

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File check-intel-io-drivers.ps1
#>

$drivers = Get-WmiObject Win32_PnPSignedDriver | Where-Object {
    $_.DeviceName -match 'Intel' -or $_.DriverProviderName -match 'Intel'
} | Select-Object DeviceName, DriverVersion, DriverDate, IsSigned

Write-Host "=== Intel Drivers Summary ==="
$drivers | Format-Table -AutoSize

Write-Host "`n=== Intel IO / Chipset / SerialIO specific ==="
$ioDrivers = Get-WmiObject Win32_PnPSignedDriver | Where-Object {
    $_.DeviceName -match '(Intel).*(IO|Chipset|SMBus|SATA|MEI|Management Engine|HECI|I2C|GPIO|SPI|UART|Serial.IO|Sensor|Thermal|PCH|RST|AHCI|USB.3|Thunderbolt|DTT|IPU)'
}
$ioDrivers | Select-Object DeviceName, DriverVersion, DriverDate | Format-Table -AutoSize

Write-Host "`n=== Total Intel drivers found: $($drivers.Count) ==="
Write-Host "=== IO/Chipset specific: $($ioDrivers.Count) ==="
