param(
    [string]$Destination = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Destination) {
    $Destination = Join-Path $projectRoot "runtime"
}
$destinationPath = [IO.Path]::GetFullPath($Destination)
$manifestPath = Join-Path $projectRoot "packaging\runtime-dependencies.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$downloads = Join-Path $destinationPath "downloads"
$expanded = Join-Path $destinationPath "expanded"
$bin = Join-Path $destinationPath "bin"
$licenses = Join-Path $destinationPath "licenses"
New-Item -ItemType Directory -Path $downloads, $expanded, $bin, $licenses -Force | Out-Null

function Get-PinnedArchive {
    param($Dependency)
    $archivePath = Join-Path $downloads $Dependency.archive
    if (Test-Path -LiteralPath $archivePath) {
        $actual = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $Dependency.sha256) {
            Remove-Item -LiteralPath $archivePath -Force
        }
    }
    if (-not (Test-Path -LiteralPath $archivePath)) {
        Write-Host "Downloading $($Dependency.url)"
        Invoke-WebRequest -Uri $Dependency.url -OutFile $archivePath
    }
    $actual = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Dependency.sha256) {
        throw "Checksum mismatch for $($Dependency.archive): expected $($Dependency.sha256), got $actual"
    }
    return $archivePath
}

function Reset-ExpandedFolder {
    param([string]$Name)
    $folder = Join-Path $expanded $Name
    $resolvedRoot = [IO.Path]::GetFullPath($expanded)
    $resolvedFolder = [IO.Path]::GetFullPath($folder)
    if (-not $resolvedFolder.StartsWith($resolvedRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw "Unsafe runtime extraction path: $resolvedFolder"
    }
    if (Test-Path -LiteralPath $resolvedFolder) {
        Remove-Item -LiteralPath $resolvedFolder -Recurse -Force
    }
    New-Item -ItemType Directory -Path $resolvedFolder -Force | Out-Null
    return $resolvedFolder
}

$ffmpegArchive = Get-PinnedArchive $manifest.ffmpeg
$ffmpegExpanded = Reset-ExpandedFolder "ffmpeg"
$sevenZip = Get-Command 7z -ErrorAction Stop
& $sevenZip.Source x $ffmpegArchive "-o$ffmpegExpanded" -y | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "7-Zip failed to extract FFmpeg."
}
$ffmpegExe = Get-ChildItem -LiteralPath $ffmpegExpanded -Filter ffmpeg.exe -File -Recurse | Select-Object -First 1
$ffprobeExe = Get-ChildItem -LiteralPath $ffmpegExpanded -Filter ffprobe.exe -File -Recurse | Select-Object -First 1
$ffmpegLicense = Get-ChildItem -LiteralPath $ffmpegExpanded -Filter LICENSE -File -Recurse | Select-Object -First 1
$ffmpegReadme = Get-ChildItem -LiteralPath $ffmpegExpanded -Filter README.txt -File -Recurse | Select-Object -First 1
if (-not $ffmpegExe -or -not $ffprobeExe -or -not $ffmpegLicense -or -not $ffmpegReadme) {
    throw "FFmpeg archive is missing expected binaries or license files."
}
Copy-Item -LiteralPath $ffmpegExe.FullName -Destination (Join-Path $bin "ffmpeg.exe") -Force
Copy-Item -LiteralPath $ffprobeExe.FullName -Destination (Join-Path $bin "ffprobe.exe") -Force
Copy-Item -LiteralPath $ffmpegLicense.FullName -Destination (Join-Path $licenses "FFmpeg-GPL-3.0.txt") -Force
Copy-Item -LiteralPath $ffmpegReadme.FullName -Destination (Join-Path $licenses "FFmpeg-BUILD-README.txt") -Force

$mpvArchive = Get-PinnedArchive $manifest.mpv
$mpvExpanded = Reset-ExpandedFolder "mpv"
Expand-Archive -LiteralPath $mpvArchive -DestinationPath $mpvExpanded -Force
$mpvExe = Get-ChildItem -LiteralPath $mpvExpanded -Filter mpv.exe -File -Recurse | Select-Object -First 1
if (-not $mpvExe) {
    throw "mpv archive is missing mpv.exe."
}
Copy-Item -LiteralPath $mpvExe.FullName -Destination (Join-Path $bin "mpv.exe") -Force
foreach ($licenseFile in $manifest.mpv.licenseFiles) {
    $licensePath = Get-PinnedArchive $licenseFile
    Copy-Item -LiteralPath $licensePath -Destination (
        Join-Path $licenses $licenseFile.archive
    ) -Force
}

$sourceNotice = @"
Pinned runtime sources

FFmpeg $($manifest.ffmpeg.version)
Binary: $($manifest.ffmpeg.url)
SHA-256: $($manifest.ffmpeg.sha256)
Source: $($manifest.ffmpeg.source)

mpv $($manifest.mpv.version)
Binary: $($manifest.mpv.url)
SHA-256: $($manifest.mpv.sha256)
Source: $($manifest.mpv.source)
"@
Set-Content -LiteralPath (Join-Path $licenses "RUNTIME-SOURCES.txt") -Value $sourceNotice -Encoding UTF8

Write-Output "RUNTIME_BIN=$bin"
Write-Output "RUNTIME_LICENSES=$licenses"
