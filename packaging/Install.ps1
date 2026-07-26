$ErrorActionPreference = "Stop"
$sourcePath = $PSScriptRoot
$sourceExecutable = Join-Path $sourcePath "TTS Dataset Studio.exe"
if (-not (Test-Path -LiteralPath $sourceExecutable)) {
    throw "TTS Dataset Studio.exe was not found beside Install.ps1."
}

$installRoot = Join-Path $env:LOCALAPPDATA "Programs\TTS Dataset Studio"
$versionsRoot = Join-Path $installRoot "versions"
$versionName = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$versionDirectory = Join-Path $versionsRoot $versionName
New-Item -ItemType Directory -Path $versionsRoot -Force | Out-Null
Copy-Item -LiteralPath $sourcePath -Destination $versionDirectory -Recurse
$installedExecutable = Join-Path $versionDirectory "TTS Dataset Studio.exe"

$programsFolder = [Environment]::GetFolderPath("Programs")
$shortcutPath = Join-Path $programsFolder "TTS Dataset Studio.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $installedExecutable
$shortcut.WorkingDirectory = $versionDirectory
$shortcut.IconLocation = "$installedExecutable,0"
$shortcut.Description = "TTS audio clip and subtitle dataset workstation"
$shortcut.Save()

$mediaExtensions = @(
    ".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus",
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"
)
$commandLine = '"{0}" "%1"' -f $installedExecutable
$applicationKey = "HKCU:\Software\Classes\Applications\TTS Dataset Studio.exe"
$applicationCommandKey = Join-Path $applicationKey "shell\open\command"
New-Item -Path $applicationCommandKey -Force | Out-Null
Set-Item -Path $applicationCommandKey -Value $commandLine
New-ItemProperty -Path $applicationKey -Name "FriendlyAppName" -Value "TTS Dataset Studio" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $applicationKey -Name "ApplicationIcon" -Value $installedExecutable -PropertyType String -Force | Out-Null

foreach ($extension in $mediaExtensions) {
    $verbKey = "HKCU:\Software\Classes\SystemFileAssociations\$extension\shell\TTSDatasetStudio"
    $verbCommandKey = Join-Path $verbKey "command"
    New-Item -Path $verbCommandKey -Force | Out-Null
    Set-Item -Path $verbKey -Value "Open with TTS Dataset Studio"
    New-ItemProperty -Path $verbKey -Name "Icon" -Value $installedExecutable -PropertyType String -Force | Out-Null
    Set-Item -Path $verbCommandKey -Value $commandLine
}

Set-Content -LiteralPath (Join-Path $installRoot "current.txt") -Value $versionDirectory -Encoding UTF8
Write-Host "Installed TTS Dataset Studio to $versionDirectory"
