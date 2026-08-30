$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $PSScriptRoot
$allowedGeneratedFiles = @(
    "data/daily-burn.sample.json",
    "data/source-status.json"
)

Push-Location $project
try {
    $branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
        throw "Dashboard publishing requires the main branch. Current branch: $branch"
    }

    $initialChanges = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the Git working tree."
    }
    if ($initialChanges.Count -gt 0) {
        throw "Dashboard publishing stopped because the working tree already has changes."
    }

    & git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) {
        throw "Could not fast-forward main from origin."
    }

    & (Join-Path $PSScriptRoot "refresh-dashboard.ps1")

    $changedFiles = @(& git diff --name-only)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect refreshed dashboard files."
    }
    $unexpectedFiles = @($changedFiles | Where-Object { $_ -notin $allowedGeneratedFiles })
    if ($unexpectedFiles.Count -gt 0) {
        throw "Refresh changed unexpected files: $($unexpectedFiles -join ', ')"
    }

    if ($changedFiles.Count -eq 0) {
        Write-Host "Dashboard data is already current; nothing to publish."
        exit 0
    }

    & git add -- $allowedGeneratedFiles
    if ($LASTEXITCODE -ne 0) {
        throw "Could not stage refreshed dashboard data."
    }

    $commitDate = Get-Date -Format "yyyy-MM-dd"
    & git commit -m "Refresh token usage data through $commitDate"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not commit refreshed dashboard data."
    }

    & git push origin main
    if ($LASTEXITCODE -ne 0) {
        throw "Could not push refreshed dashboard data."
    }

    Write-Host "Dashboard data published. Vercel will redeploy from main."
}
finally {
    Pop-Location
}
