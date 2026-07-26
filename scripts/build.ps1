param(
  [string]$RuntimeDir = "",
  [string]$DistPath = "dist",
  [string]$WorkPath = "build"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
uv sync --extra dev --frozen
if (-not $RuntimeDir) {
  $RuntimeDir = Join-Path $projectRoot "runtime"
}
$runtimeBin = Join-Path ([IO.Path]::GetFullPath($RuntimeDir)) "bin"
$ffmpeg = Join-Path $runtimeBin "ffmpeg.exe"
$ffprobe = Join-Path $runtimeBin "ffprobe.exe"
$mpvExecutable = Join-Path $runtimeBin "mpv.exe"
foreach ($required in @($ffmpeg, $ffprobe, $mpvExecutable)) {
  if (-not (Test-Path -LiteralPath $required)) {
    throw "Pinned runtime file not found: $required. Run scripts\fetch-runtime.ps1 first."
  }
}
$worker = Join-Path $projectRoot "src\tts_dataset_studio\workers\moss_worker.py"
$indexTtsWorker = Join-Path $projectRoot "src\tts_dataset_studio\workers\index_tts_worker.py"
$arguments = @(
  "--noconfirm",
  "--clean",
  "--windowed",
  "--name", "TTS Dataset Studio",
  "--distpath", $DistPath,
  "--workpath", $WorkPath,
  "--specpath", $WorkPath,
  "--add-binary", "$ffmpeg;.",
  "--add-binary", "$ffprobe;.",
  "--add-binary", "$mpvExecutable;.",
  "--add-data", "$worker;workers",
  "--add-data", "$indexTtsWorker;workers",
  "src/tts_dataset_studio/__main__.py"
)
uv run pyinstaller @arguments
