$ErrorActionPreference = "Stop"
$integrationRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $integrationRoot "..\..")).Path

function Assert-CommandVersion {
    param([string]$Name, [string]$MinimumVersion)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "$Name is required but was not found on PATH."
    }
    $versionText = (& $Name --version 2>&1 | Select-Object -First 1).ToString()
    if ($versionText -notmatch '(\d+\.\d+(?:\.\d+)?)') {
        throw "Unable to read $Name version: $versionText"
    }
    $version = [version]$Matches[1]
    if ($version -lt [version]$MinimumVersion) {
        throw "$Name $MinimumVersion or newer is required; found $version."
    }
    Write-Host "$Name $version"
}

Assert-CommandVersion -Name "node" -MinimumVersion "24.9.0"
Assert-CommandVersion -Name "python" -MinimumVersion "3.10.0"
if (-not (Get-Command "corepack" -ErrorAction SilentlyContinue)) {
    throw "Corepack is required. Install a Node.js distribution that includes Corepack."
}
if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) {
    throw "Git is required."
}

Push-Location $repoRoot
try {
    Write-Host "Installing the repository's locked workspace dependencies..."
    corepack pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "pnpm install failed with exit code $LASTEXITCODE" }

    Write-Host "Building the supported bundled Windows SDK runtime..."
    corepack pnpm exec tsx scripts/build-exe-for-python-sdk.ts
    if ($LASTEXITCODE -ne 0) { throw "SDK runtime build failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}

$venv = Join-Path $integrationRoot ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed." }
}
$pythonExe = Join-Path $venv "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $pythonExe -m pip install -r (Join-Path $integrationRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "MCP bridge dependency installation failed." }

& $pythonExe -m pip install -e (Join-Path $repoRoot "python\sdk-runtime") -e (Join-Path $repoRoot "python\sdk")
if ($LASTEXITCODE -ne 0) { throw "Local DeepSeek Harness SDK installation failed." }

Write-Host ""
Write-Host "Setup complete."
Write-Host "Next: .\integrations\chatgpt-mcp\scripts\start-windows.ps1"
