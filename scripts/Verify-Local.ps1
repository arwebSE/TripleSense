[CmdletBinding()]
param([switch]$InstallDriver)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$captureDir = Join-Path $repoRoot 'captures'
New-Item -ItemType Directory -Path $captureDir -Force | Out-Null
try {
    if ($InstallDriver) { & (Join-Path $PSScriptRoot 'Install-HostDriver.ps1') -Install }
    $pythonPath = Join-Path $repoRoot '.venv/Scripts/python.exe'
    $testPath = Join-Path $repoRoot 'tools/verify_windows.py'
    $verification = Start-Process -FilePath $pythonPath -ArgumentList ('"{0}"' -f $testPath) -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $captureDir 'windows-verify.log') -RedirectStandardError (Join-Path $captureDir 'windows-verify-error.log')
    if ($verification.ExitCode -ne 0) { throw "Windows test failed. See $captureDir\windows-verify-error.log" }
    'Windows enumeration and cleanup passed.' | Set-Content -LiteralPath (Join-Path $captureDir 'windows-verify-status.txt')
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $captureDir 'windows-verify-status.txt')
    exit 1
}
