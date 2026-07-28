param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $projectRoot "release"
}
$outputRoot = [IO.Path]::GetFullPath($OutputRoot)
$projectRootFull = [IO.Path]::GetFullPath($projectRoot)
if (-not $outputRoot.StartsWith($projectRootFull + [IO.Path]::DirectorySeparatorChar)) {
    throw "Release output must remain inside the project directory: $outputRoot"
}

$runtime = Join-Path $projectRoot "runtime"
& (Join-Path $PSScriptRoot "fetch-runtime.ps1") -Destination $runtime

$dist = Join-Path $OutputRoot "pyinstaller"
$work = Join-Path $OutputRoot "build"
& (Join-Path $PSScriptRoot "build.ps1") -RuntimeDir $runtime -DistPath $dist -WorkPath $work

$packageName = "TTS-Dataset-Studio-v$Version-windows-x64"
$staging = Join-Path $OutputRoot $packageName
if (Test-Path -LiteralPath $staging) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $dist "TTS Dataset Studio") -Destination $staging -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination $staging
Copy-Item -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_NOTICES.md") -Destination $staging
Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $staging
Copy-Item -LiteralPath (Join-Path $projectRoot "README.en.md") -Destination $staging
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\Install.ps1") -Destination $staging
Copy-Item -LiteralPath (Join-Path $runtime "licenses") -Destination (Join-Path $staging "licenses") -Recurse

$sitePackages = Join-Path $projectRoot ".venv\Lib\site-packages"
if (-not (Test-Path -LiteralPath $sitePackages)) {
    throw "Project virtual environment site-packages was not found: $sitePackages"
}
$pythonLicenses = Join-Path $staging "licenses\python"
New-Item -ItemType Directory -Path $pythonLicenses -Force | Out-Null
$licensePackages = @("pyside6-*.dist-info", "pyside6_addons-*.dist-info", "pyside6_essentials-*.dist-info", "platformdirs-*.dist-info")
foreach ($pattern in $licensePackages) {
    Get-ChildItem -LiteralPath $sitePackages -Directory -Filter $pattern | ForEach-Object {
        $licenseFolder = Join-Path $_.FullName "licenses"
        if (Test-Path -LiteralPath $licenseFolder) {
            Copy-Item -LiteralPath $licenseFolder -Destination (
                Join-Path $pythonLicenses $_.Name
            ) -Recurse
        }
    }
}

& (Join-Path $PSScriptRoot "smoke-test.ps1") -Executable (
    Join-Path $staging "TTS Dataset Studio.exe"
)

$isccCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
$isccCandidates = @(
    if ($isccCommand) { $isccCommand.Source }
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$iscc = $isccCandidates | Where-Object {
    $_ -and (Test-Path -LiteralPath $_)
} | Select-Object -First 1
if (-not $iscc -or -not (Test-Path -LiteralPath $iscc)) {
    throw "Inno Setup 6 compiler was not found. Install Inno Setup or add ISCC.exe to PATH."
}
& $iscc `
    "/DAppVersion=$Version" `
    "/DSourceDir=$staging" `
    "/DReleaseDir=$outputRoot" `
    (Join-Path $projectRoot "packaging\installer.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}
$installer = Join-Path $OutputRoot "TTS-Dataset-Studio-v$Version-setup-x64.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Expected installer was not created: $installer"
}

$zip = Join-Path $OutputRoot "$packageName.zip"
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Compress-Archive -LiteralPath $staging -DestinationPath $zip -CompressionLevel Optimal
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
$installerHash = (
    Get-FileHash -LiteralPath $installer -Algorithm SHA256
).Hash.ToLowerInvariant()
$checksumFile = Join-Path $OutputRoot "SHA256SUMS.txt"
@(
    "$zipHash  $([IO.Path]::GetFileName($zip))"
    "$installerHash  $([IO.Path]::GetFileName($installer))"
) | Set-Content -LiteralPath $checksumFile -Encoding ASCII

Write-Output "RELEASE_ZIP=$zip"
Write-Output "RELEASE_INSTALLER=$installer"
Write-Output "RELEASE_ZIP_SHA256=$zipHash"
Write-Output "RELEASE_INSTALLER_SHA256=$installerHash"
Write-Output "CHECKSUM_FILE=$checksumFile"
