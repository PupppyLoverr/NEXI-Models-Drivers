param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$releaseTag = 'b11580'
$releaseBuild = $releaseTag.TrimStart('b')
$tier = 'nexi-8gb'
$tierName = '8gb'
$ctx = 4096
$defaultModelUrl = 'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-UD-Q4_K_XL.gguf'
$expectedModelSha256 = 'b252c5610a42ca82d20fe2a12813e9d069eed89292907e26c783eeb0bc961bc7'
$assetCatalogJson = @'
{
  "windows-aarch64": {
    "name": "llama-b11580-bin-win-cpu-arm64.zip",
    "sha256": "4046b1e1b0bafc0c7b8e16a8d782d0e9da71da42e98b82c06f3c8c72489e1dc1",
    "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11580/llama-b11580-bin-win-cpu-arm64.zip"
  },
  "windows-x86_64": {
    "name": "llama-b11580-bin-win-cpu-x64.zip",
    "sha256": "430efe5b4f10db617ae0f5732f7e9360fa7be4344d1d97688e09bbd3b5b084da",
    "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11580/llama-b11580-bin-win-cpu-x64.zip"
  }
}
'@
$assetCatalog = ConvertFrom-Json $assetCatalogJson

$architecture = switch ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()) {
    'X64' { 'x86_64' }
    'Arm64' { 'aarch64' }
    default { throw "Unsupported architecture: $($_)" }
}
$platformKey = "windows-$architecture"
$assetProperty = $assetCatalog.PSObject.Properties[$platformKey]
if ($null -eq $assetProperty) {
    throw "No llama.cpp $releaseTag asset for $platformKey"
}
$asset = $assetProperty.Value

$modelUrl = $env:NEXI_MODEL_URL
if ([string]::IsNullOrWhiteSpace($modelUrl)) {
    $modelUrl = $defaultModelUrl
}
$localRoot = $env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($localRoot)) {
    $localRoot = Join-Path $HOME 'AppData/Local'
}
$installRoot = Join-Path (Join-Path $localRoot 'nexi') $tier
$binDir = Join-Path $installRoot 'bin'
$modelPath = Join-Path $installRoot 'model.gguf'
$archivePath = Join-Path $installRoot $asset.name
$launcherPath = Join-Path $installRoot "nexi-$tierName-serve.cmd"

if ($DryRun) {
    Write-Output "Target platform: $platformKey"
    Write-Output "llama.cpp asset: $($asset.name)"
    Write-Output "llama.cpp asset URL: $($asset.url)"
    Write-Output "llama.cpp archive path: $archivePath"
    Write-Output "Model URL: $modelUrl"
    Write-Output "Model path: $modelPath"
    Write-Output "Binary path: $(Join-Path $binDir 'llama-server.exe')"
    Write-Output "Launcher path: $launcherPath"
    Write-Output 'OpenAI-compatible endpoint: http://127.0.0.1:8391/v1'
    exit 0
}

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw 'install.ps1 installs on Windows; use -DryRun to inspect it on another platform.'
}

New-Item -ItemType Directory -Force -Path $installRoot, $binDir | Out-Null

if (Test-Path -LiteralPath $modelPath -PathType Leaf) {
    $currentModelSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $modelPath).Hash
}
else {
    $currentModelSha256 = ''
}
if ($currentModelSha256 -ine $expectedModelSha256) {
    $modelPart = "$modelPath.part"
    Invoke-WebRequest -Uri $modelUrl -OutFile $modelPart
    $downloadedModelSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $modelPart).Hash
    if ($downloadedModelSha256 -ine $expectedModelSha256) {
        Remove-Item -Force -LiteralPath $modelPart
        throw "Model SHA-256 mismatch: $modelUrl"
    }
    Move-Item -Force -LiteralPath $modelPart -Destination $modelPath
}
else {
    Write-Output "Using verified model: $modelPath"
}

if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    $currentAssetSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash
}
else {
    $currentAssetSha256 = ''
}
if ($currentAssetSha256 -ine $asset.sha256) {
    $archivePart = "$archivePath.part"
    Invoke-WebRequest -Uri $asset.url -OutFile $archivePart
    $downloadedAssetSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePart).Hash
    if ($downloadedAssetSha256 -ine $asset.sha256) {
        Remove-Item -Force -LiteralPath $archivePart
        throw "llama.cpp asset SHA-256 mismatch: $($asset.url)"
    }
    Move-Item -Force -LiteralPath $archivePart -Destination $archivePath
}
else {
    Write-Output "Using verified llama.cpp asset: $archivePath"
}

$markerPath = Join-Path $installRoot ".llama-$releaseTag.verified"
$markerValue = "$releaseTag`:$($asset.sha256)"
$serverPath = Join-Path $binDir 'llama-server.exe'
$installed = $false
if ((Test-Path -LiteralPath $serverPath -PathType Leaf) -and
    (Test-Path -LiteralPath $markerPath -PathType Leaf) -and
    ((Get-Content -Raw -LiteralPath $markerPath) -eq $markerValue)) {
    $versionOutput = (& $serverPath --version 2>&1 | Out-String)
    $installed = ($LASTEXITCODE -eq 0 -and $versionOutput -match "(?i)\bbuild\s+$releaseBuild\b")
}

if (-not $installed) {
    $extractDir = Join-Path $installRoot "extract-$PID"
    if (Test-Path -LiteralPath $extractDir) {
        Remove-Item -Recurse -Force -LiteralPath $extractDir
    }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDir -Force
    $serverFile = Get-ChildItem -LiteralPath $extractDir -Filter 'llama-server.exe' -File -Recurse |
        Select-Object -First 1
    if ($null -eq $serverFile) {
        Remove-Item -Recurse -Force -LiteralPath $extractDir
        throw "llama-server.exe was not found in $($asset.name)"
    }
    Copy-Item -Path (Join-Path $serverFile.Directory.FullName '*') -Destination $binDir -Recurse -Force
    Remove-Item -Recurse -Force -LiteralPath $extractDir
    $versionOutput = (& $serverPath --version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "(?i)\bbuild\s+$releaseBuild\b") {
        throw "Unexpected llama-server version: $versionOutput"
    }
    Set-Content -NoNewline -Encoding ascii -LiteralPath $markerPath -Value $markerValue
}

$physicalCoreTotal = (Get-CimInstance -ClassName Win32_Processor |
    Measure-Object -Property NumberOfCores -Sum).Sum
if ($physicalCoreTotal -lt 1) {
    throw 'Could not determine the physical CPU core count.'
}
$launcherContent = @'
@echo off
setlocal
"%~dp0bin\llama-server.exe" -m "%~dp0model.gguf" -c __NEXI_CTX__ --jinja --host 127.0.0.1 --port 8391 -t __NEXI_PHYSICAL_CORES__ %*
'@
$launcherContent = $launcherContent.Replace('__NEXI_CTX__', [string]$ctx)
$launcherContent = $launcherContent.Replace('__NEXI_PHYSICAL_CORES__', [string]$physicalCoreTotal)
Set-Content -Encoding ascii -LiteralPath $launcherPath -Value $launcherContent

Write-Output "Launcher: $launcherPath"
Write-Output 'OpenAI-compatible endpoint: http://127.0.0.1:8391/v1'
