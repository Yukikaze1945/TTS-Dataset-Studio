param(
    [Parameter(Mandatory = $true)]
    [string]$Executable
)

$ErrorActionPreference = "Stop"
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$process = Start-Process -FilePath $resolvedExecutable -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Seconds 6
    if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
        throw "Application exited during startup smoke test."
    }

    # The player process is intentionally lazy and starts only after media is
    # loaded. Verify the bundled executable directly instead of requiring a
    # child process from an empty project.
    $applicationRoot = Split-Path -Parent $resolvedExecutable
    $mpvExecutable = Join-Path $applicationRoot "_internal\mpv.exe"
    if (-not (Test-Path -LiteralPath $mpvExecutable -PathType Leaf)) {
        throw "Bundled mpv executable was not found: $mpvExecutable"
    }
    & $mpvExecutable --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Bundled mpv executable failed its version check."
    }
    Write-Output "SMOKE_TEST_OK=$resolvedExecutable"
}
finally {
    if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
        Stop-Process -Id $process.Id -Force
    }
}
