$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root
try {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 (Join-Path $root "dashboard.py") }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python (Join-Path $root "dashboard.py") }
    else { throw "Python 3 was not found on PATH." }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }