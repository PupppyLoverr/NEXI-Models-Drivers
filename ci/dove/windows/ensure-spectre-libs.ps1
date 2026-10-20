# Make sure the VS "MSVC Spectre-mitigated libs" component is installed (ROADMAP R0.5).
#
# regorus turns on msvc_spectre_libs with `error`, so a Windows build fails
# without Microsoft.VisualStudio.Component.VC.Runtimes.x86.x64.Spectre.
# GitHub's Windows images may already carry it; this installs it only when
# the Spectre lib folder is missing, then fails unless it is present.
# For CI runners only: it modifies the Visual Studio installation. -CheckOnly
# reports and exits 1 when the libs are missing, without installing anything.
param([switch]$CheckOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$component = "Microsoft.VisualStudio.Component.VC.Runtimes.x86.x64.Spectre"
$installerDir = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer"
$vswhere = Join-Path $installerDir "vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found at $vswhere" }

$vs = & $vswhere -latest -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "no Visual Studio installation with the x64 C++ tools" }
Write-Host "Visual Studio: $vs"

function Get-SpectreLibDirs {
    @(Get-ChildItem -Path (Join-Path $vs "VC\Tools\MSVC\*\lib\spectre\x64") -Directory -ErrorAction SilentlyContinue)
}

if (@(Get-SpectreLibDirs).Count -gt 0) {
    Write-Host "Spectre-mitigated libs already installed: $(@(Get-SpectreLibDirs).FullName -join ', ')"
    exit 0
}
if ($CheckOnly) {
    Write-Host "Spectre-mitigated libs are not installed ($component)"
    exit 1
}

Write-Host "Installing $component"
$setup = Join-Path $installerDir "setup.exe"
$installArgs = @("modify", "--installPath", "`"$vs`"", "--add", $component,
    "--quiet", "--norestart", "--nocache")
$process = Start-Process -FilePath $setup -ArgumentList $installArgs -Wait -PassThru -NoNewWindow
# 3010 = success, reboot required (not needed for libraries).
if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
    throw "Visual Studio installer exited with $($process.ExitCode)"
}
if (@(Get-SpectreLibDirs).Count -eq 0) {
    throw "$component reported success but no VC\Tools\MSVC\*\lib\spectre\x64 folder exists"
}
Write-Host "Spectre-mitigated libs installed: $(@(Get-SpectreLibDirs).FullName -join ', ')"
