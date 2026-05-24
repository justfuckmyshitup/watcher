[CmdletBinding()]
param(
  [string]$PythonVersion = "3.12",
  [switch]$ForceRecreateVenv,
  [switch]$InstallRuntimePackages,
  [switch]$DownloadModels,
  [switch]$SkipPaddle,
  [switch]$SkipOnnxGenai
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-WatcherRepoRoot
Set-Location $repoRoot

function Get-WatcherPythonVersionText {
  param([string]$Python)
  $output = & $Python --version 2>&1
  if ($LASTEXITCODE -ne 0) {
    return ""
  }
  return ($output -join " ").Trim()
}

function Test-WatcherPythonSupportsMl {
  param([string]$VersionText)
  return $VersionText -match "Python 3\.(12|13)\."
}

function Resolve-WatcherMlPython {
  $py = Get-WatcherCommand @("py.exe", "py")
  if ($py) {
    $oldPreference = $ErrorActionPreference
    try {
      $ErrorActionPreference = "Continue"
      $candidate = & $py "-$PythonVersion" "-c" "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $candidate) {
        return ($candidate -join "").Trim()
      }
    } finally {
      $ErrorActionPreference = $oldPreference
    }
  }
  $python = Get-WatcherCommand @("python.exe", "python")
  if ($python -and (Test-WatcherPythonSupportsMl (Get-WatcherPythonVersionText $python))) {
    return $python
  }
  return $null
}

$python = Resolve-WatcherMlPython
if (-not $python) {
  Write-WatcherErrorMessage "Python $PythonVersion was not found. Live PaddleOCR/ONNX GenAI profiles need Python 3.12 or 3.13."
  Write-Host "Install manually, then rerun:"
  Write-Host "  winget install -e --id Python.Python.3.12"
  exit 1
}

$version = Get-WatcherPythonVersionText $python
Write-WatcherStatus "Using $version at $python"

$venvDir = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
  $venvVersion = Get-WatcherPythonVersionText $venvPython
  if (-not (Test-WatcherPythonSupportsMl $venvVersion)) {
    if (-not $ForceRecreateVenv) {
      Write-WatcherErrorMessage ".venv is $venvVersion, which is not suitable for the live GPU OCR/LLM POC."
      Write-Host "Rerun with -ForceRecreateVenv to move the old .venv aside and create a Python $PythonVersion environment."
      exit 1
    }
    $backup = Join-Path $repoRoot ".venv-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Write-WatcherWarn "Moving existing .venv to $backup"
    Move-Item -LiteralPath $venvDir -Destination $backup
  }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
  Write-WatcherStatus "Creating .venv with $version..."
  & $python -m venv .venv
  if ($LASTEXITCODE -ne 0) {
    Write-WatcherErrorMessage "Failed to create .venv."
    exit $LASTEXITCODE
  }
}

Write-WatcherStatus "Installing backend requirements..."
& $venvPython -m pip install -r (Join-Path $repoRoot "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) {
  Write-WatcherErrorMessage "Backend dependency install failed."
  exit $LASTEXITCODE
}

if ($InstallRuntimePackages) {
  Write-WatcherStatus "Installing Hugging Face download tooling..."
  & $venvPython -m pip install -U "huggingface_hub[hf_xet]"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  if (-not $SkipOnnxGenai) {
    Write-WatcherStatus "Installing ONNX Runtime GenAI CUDA package..."
    & $venvPython -m pip install --pre onnxruntime-genai-cuda
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }

  if (-not $SkipPaddle) {
    Write-WatcherStatus "Installing PaddlePaddle GPU and PaddleOCR packages..."
    & $venvPython -m pip install "paddlepaddle-gpu==3.2.0" -i "https://www.paddlepaddle.org.cn/packages/stable/cu126/"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $venvPython -m pip install paddleocr
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
} else {
  Write-WatcherWarn "Runtime packages were not installed. Rerun with -InstallRuntimePackages when ready."
}

if ($DownloadModels) {
  Write-WatcherStatus "Downloading local Hugging Face model profile..."
  & "$PSScriptRoot\download-models.ps1" -Profile poc
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}

Write-WatcherStatus "Live POC setup check:"
& "$PSScriptRoot\check-gpu.ps1" -RequireGpu
& "$PSScriptRoot\check-models.ps1" -Profile poc
if (-not $SkipPaddle) {
  & "$PSScriptRoot\check-ocr.ps1" -Provider paddle -Profile screen-fast -RequireGpu
}
