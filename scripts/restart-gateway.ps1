<#
.SYNOPSIS
    Restart the 1min.ai gateway's Windows Scheduled Task and wait for it to
    come back healthy.

.DESCRIPTION
    installGateway() (run by the OpenCode plugin on every startup) is a
    deliberate no-op once the gateway is already healthy, and the gateway
    process itself never reloads its own code (uvicorn runs without
    --reload, no file watcher). That means editing gateway/src alone -- even
    with the editable `pip install -e` -- never takes effect on its own.
    This script is the explicit, one-shot fix: end the running task
    instance, start a fresh one, and poll /health until it responds.

    Safe to run any time; ending a task that isn't running is a no-op.
#>

$ErrorActionPreference = "Stop"

$serviceName = "OneMinGateway"
$configPath = Join-Path $env:APPDATA "1min-gateway\config.json"

$gwHost = "127.0.0.1"
$port = 8765
if (Test-Path $configPath) {
    try {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
        if ($config.host) { $gwHost = $config.host }
        if ($config.port) { $port = $config.port }
    } catch {
        Write-Warning "Could not parse $configPath, falling back to defaults ($gwHost`:$port)."
    }
} else {
    Write-Warning "Config not found at $configPath, falling back to defaults ($gwHost`:$port)."
}

$healthUrl = "http://$($gwHost):$($port)/health"

Write-Host "Restarting scheduled task '$serviceName'..."
schtasks /End /TN $serviceName | Out-Null
schtasks /Run /TN $serviceName | Out-Null

$healthy = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        if ($response.status -eq "ok") {
            $healthy = $true
            break
        }
    } catch {
        # Not up yet -- keep polling.
    }
}

if ($healthy) {
    Write-Host "Gateway restarted and healthy at $healthUrl"
    exit 0
} else {
    $logPath = Join-Path $env:APPDATA "1min-gateway\gateway.log"
    Write-Host "Gateway restart issued but $healthUrl did not report healthy within 10s."
    Write-Host "Check $logPath for errors."
    exit 1
}
