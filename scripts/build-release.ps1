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

$zip = Join-Path $OutputRoot "$packageName.zip"
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Compress-Archive -LiteralPath $staging -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumFile = Join-Path $OutputRoot "SHA256SUMS.txt"
Set-Content -LiteralPath $checksumFile -Value "$hash  $([IO.Path]::GetFileName($zip))" -Encoding ASCII

Write-Output "RELEASE_ZIP=$zip"
Write-Output "RELEASE_SHA256=$hash"
Write-Output "CHECKSUM_FILE=$checksumFile"
