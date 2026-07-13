$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $PSScriptRoot
$bundledNodeBin = "C:\Users\treeb\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$pythonCandidates = @(
    "C:\Users\treeb\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
    (Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$pythonCandidates = @($pythonCandidates)

$packageManagerCandidates = @(
    "C:\Users\treeb\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\pnpm.cmd",
    (Get-Command pnpm.cmd -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
    (Get-Command npm.cmd -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$packageManagerCandidates = @($packageManagerCandidates)

if (-not $pythonCandidates) {
    throw "Python runtime not found."
}

if (-not $packageManagerCandidates) {
    throw "Node package manager not found."
}

if (Test-Path -LiteralPath $bundledNodeBin) {
    $env:Path = "$bundledNodeBin;$env:Path"
}
$env:CI = "true"

& $pythonCandidates[0] (Join-Path $PSScriptRoot "refresh-dashboard.py")
if ($LASTEXITCODE -ne 0) {
    throw "Dashboard data refresh failed."
}

Push-Location $project
try {
    & $packageManagerCandidates[0] run build
    if ($LASTEXITCODE -ne 0) {
        throw "Dashboard build failed."
    }
}
finally {
    Pop-Location
}
