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
    $mpv = Get-CimInstance Win32_Process |
        Where-Object { $_.ParentProcessId -eq $process.Id -and $_.Name -eq "mpv.exe" }
    if (-not $mpv) {
        throw "Bundled mpv child process was not started."
    }
    Write-Output "SMOKE_TEST_OK=$resolvedExecutable"
}
finally {
    if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
        Stop-Process -Id $process.Id -Force
    }
}
