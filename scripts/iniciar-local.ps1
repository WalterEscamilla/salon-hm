$ErrorActionPreference = 'Stop'
$salonRoot = Split-Path -Parent $PSScriptRoot
$salonPython = Join-Path $salonRoot '.venv\Scripts\python.exe'
$salonLogs = Join-Path $salonRoot '.tools'
if (-not (Test-Path -LiteralPath $salonPython)) {
    throw 'Prepara el entorno .venv siguiendo el README antes de iniciar el salon.'
}
New-Item -ItemType Directory -Path $salonLogs -Force | Out-Null

function Proceso-SalonActivo([string]$patron) {
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match $patron -and $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($salonRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)
    }).Count -gt 0
}

if (-not (Proceso-SalonActivo 'manage\.py runserver 127\.0\.0\.1:8010')) {
    if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) {
        throw 'El puerto 8010 esta ocupado por otro proceso; no se inicia un segundo servidor.'
    }
    Start-Process -FilePath $salonPython -ArgumentList @('manage.py', 'runserver', '127.0.0.1:8010') -WorkingDirectory $salonRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $salonLogs 'servidor-local.log') -RedirectStandardError (Join-Path $salonLogs 'servidor-local-error.log') | Out-Null
}
if (-not (Proceso-SalonActivo 'manage\.py sincronizar_calendario --continuo')) {
    Start-Process -FilePath $salonPython -ArgumentList @('manage.py', 'sincronizar_calendario', '--continuo') -WorkingDirectory $salonRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $salonLogs 'calendario-local.log') -RedirectStandardError (Join-Path $salonLogs 'calendario-local-error.log') | Out-Null
}
Write-Output 'Salon y procesador de Calendar activos. Abre http://127.0.0.1:8010/.'
