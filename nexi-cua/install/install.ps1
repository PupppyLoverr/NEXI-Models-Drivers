[CmdletBinding()]
param(
    [switch]$WithVision,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

if ($env:NEXI_CUA_HOME) {
    $NexiHome = $env:NEXI_CUA_HOME
} else {
    $NexiHome = Join-Path $env:LOCALAPPDATA 'nexi-cua'
}
$Venv = Join-Path $NexiHome 'venv'
$BinDirectory = Join-Path $NexiHome 'bin'
$CommandPath = Join-Path $BinDirectory 'nexi-cua.cmd'

if ($Uninstall) {
    if (Test-Path -LiteralPath $CommandPath) {
        Remove-Item -LiteralPath $CommandPath -Force
    }
    if (Test-Path -LiteralPath $Venv) {
        Remove-Item -LiteralPath $Venv -Recurse -Force
    }
    Write-Output "Removed $Venv and $CommandPath"
    exit 0
}

$Python = $null
$PythonArguments = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = 'py'
    $PythonArguments = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = 'python'
} else {
    throw 'Python 3.10 or newer is required; install Python 3 and try again.'
}

$PythonVersion = & $Python @PythonArguments -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -ne 0 -or [version]$PythonVersion -lt [version]'3.10') {
    throw "Python 3.10 or newer is required; found $PythonVersion."
}

New-Item -ItemType Directory -Path $NexiHome -Force | Out-Null
& $Python @PythonArguments -m venv $Venv
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to create the Python virtual environment.'
}

$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Extra = 'windows'
$CheckoutManifest = Join-Path $PSScriptRoot '..\pyproject.toml'
if (Test-Path -LiteralPath $CheckoutManifest) {
    $Checkout = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $PackageSpec = "$Checkout[$Extra]"
} else {
    $PackageSpec = 'nexi-cua[windows] @ https://github.com/PupppyLoverr/gabbledobo-71588/raw/main/nexi-cua/releases/nexi_cua-0.4.0-py3-none-any.whl'
}
& $VenvPython -m pip install $PackageSpec
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install nexi-cua.'
}

$VenvCommand = Join-Path $Venv 'Scripts\nexi-cua.exe'
New-Item -ItemType Directory -Path $BinDirectory -Force | Out-Null
Set-Content -LiteralPath $CommandPath -Value "@echo off`r`n`"$VenvCommand`" %*" -Encoding ASCII
Write-Output "Installed nexi-cua. Add $BinDirectory to your PATH."

if ($WithVision) {
    Write-Output 'For llama.cpp vision weights, run: nexi-cua download-weights'
}

& $VenvCommand doctor
if ($LASTEXITCODE -ne 0) {
    throw 'nexi-cua doctor reported a problem.'
}
