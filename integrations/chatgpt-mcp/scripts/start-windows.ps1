$ErrorActionPreference = "Stop"
$integrationRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $integrationRoot "..\..")).Path
$pythonExe = Join-Path $integrationRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Bridge is not installed. Run integrations\chatgpt-mcp\scripts\setup-windows.ps1 first."
}
$cloudflaredCommand = Get-Command "cloudflared" -ErrorAction SilentlyContinue
if (-not $cloudflaredCommand) {
    throw "cloudflared is required. Install it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ and rerun this script."
}

$logs = Join-Path $integrationRoot "logs"
$secrets = Join-Path $integrationRoot "secrets"
$dshHome = Join-Path $integrationRoot ".dsh-home"
New-Item -ItemType Directory -Force -Path $logs, $secrets, $dshHome | Out-Null

$tokenFile = Join-Path $secrets "mcp-bearer-token.txt"
if (-not (Test-Path $tokenFile)) {
    $bytes = [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    $token = [Convert]::ToHexString($bytes).ToLowerInvariant()
    [IO.File]::WriteAllText($tokenFile, $token)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $tokenFile /inheritance:r /grant:r ("{0}:(F)" -f $identity) | Out-Null
}
$env:MCP_BEARER_TOKEN = (Get-Content -Raw $tokenFile).Trim()
$env:DSH_HOME = $dshHome
$env:DSH_WORKSPACE_ROOT = $repoRoot
$env:MCP_PORT = "8765"
$env:DSH_TELEMETRY_DISABLED = "1"
$env:PYTHONPATH = Join-Path $integrationRoot "src"

if (-not $env:DEEPSEEK_API_KEY) {
    $secureKey = Read-Host "Enter your DeepSeek API key (input is hidden)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
        $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}
if (-not $env:DEEPSEEK_API_KEY) {
    throw "DEEPSEEK_API_KEY is required."
}

$serverOut = Join-Path $logs "server.out.log"
$serverErr = Join-Path $logs "server.err.log"
$tunnelOut = Join-Path $logs "cloudflared.out.log"
$tunnelErr = Join-Path $logs "cloudflared.err.log"
$server = $null
$tunnel = $null

try {
    $server = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "deepseek_harness_mcp.server") -WorkingDirectory $integrationRoot -PassThru -NoNewWindow -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr
    $localReady = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        if ($server.HasExited) { throw "MCP server exited during startup. Inspect $serverErr" }
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:8765/healthz" -Headers @{ Authorization = "Bearer $env:MCP_BEARER_TOKEN" } -TimeoutSec 2 | Out-Null
            $localReady = $true
            break
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $localReady) { throw "MCP server did not become ready. Inspect $serverErr" }

    $tunnel = Start-Process -FilePath $cloudflaredCommand.Source -ArgumentList @("tunnel", "--url", "http://127.0.0.1:8765", "--output", "json") -PassThru -NoNewWindow -RedirectStandardOutput $tunnelOut -RedirectStandardError $tunnelErr
    $endpoint = $null
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($tunnel.HasExited) { throw "cloudflared exited during startup. Inspect $tunnelErr" }
        foreach ($logFile in @($tunnelOut, $tunnelErr)) {
            if (Test-Path $logFile) {
                $content = Get-Content -Raw $logFile
                if ($content -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
                    $endpoint = $Matches[0] + "/mcp"
                    break
                }
            }
        }
        if ($endpoint) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $endpoint) { throw "No Quick Tunnel URL was detected. Inspect $tunnelOut and $tunnelErr" }

    Write-Host ""
    Write-Host "DeepSeek Harness MCP is ready."
    Write-Host "MCP endpoint: $endpoint"
    Write-Host "Bearer token is stored locally at: $tokenFile"
    Write-Host "Do not paste the bearer token or DeepSeek API key into chat."
    Write-Host "Keep this window open. Press Ctrl+C to stop the tunnel and local bridge."
    Write-Host ""
    Write-Host "Send only the MCP endpoint URL in this ChatGPT conversation so the private plugin can be packaged."
    Wait-Process -Id $tunnel.Id
}
finally {
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "Local MCP bridge stopped."
}
