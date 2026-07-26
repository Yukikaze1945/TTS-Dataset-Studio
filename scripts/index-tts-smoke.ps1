param(
    [Parameter(Mandatory = $true)]
    [string]$IndexTtsRoot,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "index_tts_smoke.py"
$arguments = @($script, "--root", $IndexTtsRoot)
if ($Output) {
    $arguments += @("--output", $Output)
}
uv run python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "IndexTTS2 smoke test failed with exit code $LASTEXITCODE."
}
