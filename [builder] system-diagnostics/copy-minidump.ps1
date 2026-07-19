# Copy minidump files to user-accessible location (elevated)
# Usage: powershell -ExecutionPolicy Bypass -File copy-minidump.ps1
# The cmd.exe -Verb RunAs triggers a UAC prompt; user must click Yes.

$srcDir = "C:\Windows\Minidump"
$dstDir = $env:USERPROFILE

# Build copy commands
$cmds = @('/c')
Get-ChildItem $srcDir -Filter "*.dmp" -ErrorAction SilentlyContinue | ForEach-Object {
    $cmds += "copy /Y `"$($_.FullName)`" `"$dstDir\$($_.Name)`" &&"
}
$cmds[-1] = $cmds[-1].TrimEnd("&&")  # remove trailing &&
$cmds += "&"  # keep window open on error

$arg = $cmds -join " "
Start-Process cmd.exe -ArgumentList $arg -Verb RunAs -Wait -WindowStyle Normal

# Verify
$copied = Get-ChildItem $dstDir -Filter "minidump_copy*.dmp" -ErrorAction SilentlyContinue
if ($copied) {
    Write-Host ("Copied {0} dump(s):" -f $copied.Count)
    $copied | ForEach-Object { Write-Host ("  " + $_.Name + " (" + $_.Length.ToString("N0") + " bytes)") }
} else {
    Write-Host "No dumps found or copy failed. Check C:\Windows\Minidump\ exists."
}
