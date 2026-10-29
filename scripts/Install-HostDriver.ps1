[CmdletBinding()]
param([switch]$Install)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$cacheDir = Join-Path $repoRoot '.driver'
$installerPath = Join-Path $cacheDir 'USBip-0.9.8.1-x64.exe'
$expectedHash = '38cad6d4432b52d5bb9409d9ad03b72fdffc4ada4cd3a48fbeca1a2752a8518a'
$downloadUrl = 'https://github.com/vadimgrn/usbip-win2/releases/download/v.0.9.8.1/USBip-0.9.8.1-x64.exe'

if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'This pinned installer targets x64 Windows. ARM64 needs a separately verified asset.'
}
New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $installerPath)) {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
}
$actualHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) { throw 'Installer SHA-256 mismatch; refusing to execute.' }
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
if ($signature.Status -ne 'Valid') { throw "Invalid installer signature: $($signature.Status)" }
Write-Output "Verified USBip 0.9.8.1: $($signature.SignerCertificate.Subject)"

if (-not $Install) {
    Write-Output 'Download verified. To install, run this script with -Install in an Administrator PowerShell.'
    return
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Driver installation requires Administrator PowerShell. No system settings were changed.'
}
if ((Test-Path -LiteralPath 'C:\Program Files\USBip\usbip.exe') -or
    (Get-Service -Name usbip2_ude,usbip2_filter -ErrorAction SilentlyContinue)) {
    throw 'An existing USB/IP driver was found. Review its version and devices before upgrading it.'
}
$logPath = Join-Path $cacheDir 'install.log'
$installerArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="{0}"' -f $logPath))
$process = Start-Process -FilePath $installerPath -ArgumentList $installerArgs -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -notin @(0, 3010)) { throw "Installer exit code $($process.ExitCode). See $logPath" }
if ($process.ExitCode -eq 3010) { Write-Output 'Windows requested a restart; no restart was performed.' }
Write-Output 'Driver installer finished. Run ds5driver doctor and verify live attachment before playing.'
