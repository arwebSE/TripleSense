param([int]$ParentId, [string]$Package, [string]$App, [string]$Log)
$ErrorActionPreference = 'Stop'
try {
    if (Get-Process -Id $ParentId -ErrorAction SilentlyContinue) {
        Wait-Process -Id $ParentId -Timeout 120 -ErrorAction Stop
    }
    $installer = Start-Process -FilePath $Package -ArgumentList '/SILENT','/SUPPRESSMSGBOXES','/NORESTART' -Verb RunAs -Wait -PassThru
    if ($installer.ExitCode -ne 0) { throw "Installer exited with code $($installer.ExitCode)" }
} catch {
    $_ | Out-File -LiteralPath $Log -Append
    if (Get-Process -Id $ParentId -ErrorAction SilentlyContinue) { exit 1 }
}
Start-Process -FilePath $App
