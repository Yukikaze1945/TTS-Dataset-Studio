param(
    [string]$SourcePath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $SourcePath) {
    $SourcePath = Join-Path $projectRoot "dist-latest\TTS Dataset Studio"
}

$resolvedSource = (Resolve-Path -LiteralPath $SourcePath).Path
$sourceExecutable = Join-Path $resolvedSource "TTS Dataset Studio.exe"
if (-not (Test-Path -LiteralPath $sourceExecutable)) {
    throw "TTS Dataset Studio.exe was not found in source: $resolvedSource"
}

$installRoot = Join-Path $env:LOCALAPPDATA "Programs\TTS Dataset Studio"
$versionsRoot = Join-Path $installRoot "versions"
$versionName = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$versionDirectory = Join-Path $versionsRoot $versionName

New-Item -ItemType Directory -Path $versionsRoot -Force | Out-Null
Copy-Item -LiteralPath $resolvedSource -Destination $versionDirectory -Recurse

$installedExecutable = Join-Path $versionDirectory "TTS Dataset Studio.exe"
if (-not (Test-Path -LiteralPath $installedExecutable)) {
    throw "Installed executable was not found: $installedExecutable"
}

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
$supportedTypesKey = Join-Path $applicationKey "SupportedTypes"

New-Item -Path $applicationCommandKey -Force | Out-Null
Set-Item -Path $applicationCommandKey -Value $commandLine
New-ItemProperty -Path $applicationKey -Name "FriendlyAppName" -Value "TTS Dataset Studio" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $applicationKey -Name "ApplicationIcon" -Value $installedExecutable -PropertyType String -Force | Out-Null
New-Item -Path $supportedTypesKey -Force | Out-Null

foreach ($extension in $mediaExtensions) {
    New-ItemProperty -Path $supportedTypesKey -Name $extension -Value "" -PropertyType String -Force | Out-Null

    $openWithKey = "HKCU:\Software\Classes\$extension\OpenWithList\TTS Dataset Studio.exe"
    New-Item -Path $openWithKey -Force | Out-Null

    $verbKey = "HKCU:\Software\Classes\SystemFileAssociations\$extension\shell\TTSDatasetStudio"
    $verbCommandKey = Join-Path $verbKey "command"
    New-Item -Path $verbCommandKey -Force | Out-Null
    Set-Item -Path $verbKey -Value "Open with TTS Dataset Studio"
    New-ItemProperty -Path $verbKey -Name "Icon" -Value $installedExecutable -PropertyType String -Force | Out-Null
    Set-Item -Path $verbCommandKey -Value $commandLine
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class TtsStudioShellRefresh {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(uint eventId, uint flags, IntPtr item1, IntPtr item2);
}
"@
[TtsStudioShellRefresh]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)

Set-Content -LiteralPath (Join-Path $installRoot "current.txt") -Value $versionDirectory -Encoding UTF8

Write-Output "INSTALLED_EXE=$installedExecutable"
Write-Output "START_MENU_SHORTCUT=$shortcutPath"
Write-Output "CONTEXT_MENU_EXTENSIONS=$($mediaExtensions -join ',')"
