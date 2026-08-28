$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Push-Location $Root
try {
    Invoke-Checked { & $Python -m pip check }
    Invoke-Checked { & $Python -m pip_audit }
    Invoke-Checked { & $Python -m pytest -q }
    Invoke-Checked { & $Python -m ruff check . }
    Invoke-Checked { & $Python scripts\release_scan.py }
    Push-Location (Join-Path $Root "frontend")
    try {
        Invoke-Checked { npm test }
        Invoke-Checked { npm run build }
        Invoke-Checked { npm audit --audit-level=low --registry=https://registry.npmjs.org }
    }
    finally {
        Pop-Location
    }
    Invoke-Checked { git diff --check }
}
finally {
    Pop-Location
}
