[CmdletBinding()]
param(
  [string]$Provider = "paddle",
  [string]$Profile = "screen-fast",
  [switch]$RequireGpu,
  [switch]$AllowCpuFallback,
  [switch]$Json,
  [string]$PythonPath
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-WatcherRepoRoot
Set-Location $repoRoot

function Resolve-WatcherPythonForOcr {
  if ($PythonPath) {
    return $PythonPath
  }
  $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) {
    return $venvPython
  }
  return Get-WatcherCommand @("python.exe", "python")
}

$python = Resolve-WatcherPythonForOcr
if (-not $python) {
  Write-WatcherErrorMessage "Python was not found. Create .venv or install Python, then rerun this script."
  exit 1
}

$ocrRequiresGpu = $RequireGpu -and -not $AllowCpuFallback
$env:WATCHER_OCR_PROVIDER = $Provider
$env:WATCHER_OCR_PROFILE = $Profile
$env:WATCHER_OCR_REQUIRE_GPU = if ($ocrRequiresGpu) { "true" } else { "false" }

$probeDir = Join-Path $repoRoot "app-data\tmp\ocr-probe"
Ensure-WatcherDirectory $probeDir
$probePath = Join-Path $probeDir "ocr-provider-probe-$([guid]::NewGuid().ToString('N')).py"
$code = @'
import json
from backend.app.ocr.providers import get_ocr_provider

provider = get_ocr_provider()
print(json.dumps(provider.diagnostics(), default=str))
'@

try {
  $code | Set-Content -LiteralPath $probePath -Encoding UTF8
  $oldPythonPath = $env:PYTHONPATH
  if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
    $env:PYTHONPATH = $repoRoot
  } else {
    $env:PYTHONPATH = "$repoRoot;$oldPythonPath"
  }
  $oldErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $output = & $python $probePath 2>&1
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $oldErrorActionPreference
  }
  if ($exitCode -ne 0 -or -not $output) {
    throw "OCR diagnostics probe failed. $($output -join "`n")"
  }
  $jsonLine = @($output | ForEach-Object { [string]$_ } | Where-Object { $_.TrimStart().StartsWith("{") } | Select-Object -Last 1)
  if (-not $jsonLine) {
    throw "OCR diagnostics probe did not return JSON. $($output -join "`n")"
  }
  $diagnostics = ($jsonLine | ConvertFrom-Json)
} finally {
  $env:PYTHONPATH = $oldPythonPath
  if (Test-Path -LiteralPath $probePath) {
    Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
  }
  try {
    $remaining = Get-ChildItem -Force -LiteralPath $probeDir -ErrorAction SilentlyContinue
    if (-not $remaining) {
      Remove-Item -LiteralPath $probeDir -Force -ErrorAction SilentlyContinue
    }
  } catch {
    $null = $_
  }
}

if ($Json) {
  $diagnostics | ConvertTo-Json -Depth 10
} else {
  Write-WatcherStatus "OCR provider: $($diagnostics.provider)"
  Write-WatcherStatus "OCR profile: $($diagnostics.profile)"
  Write-WatcherStatus "OCR available: $($diagnostics.available)"
  if ($diagnostics.device) {
    Write-WatcherStatus "OCR device: $($diagnostics.device)"
  }
  if ($diagnostics.reasons -and $diagnostics.reasons.Count -gt 0) {
    foreach ($reason in $diagnostics.reasons) {
      Write-WatcherWarn "OCR readiness: $reason"
    }
  }
  if ($diagnostics.provider -eq "paddle" -and -not $diagnostics.available) {
    Write-WatcherStatus "Manual install guidance:"
    Write-Host "  python -m pip install paddleocr"
    Write-Host "  python -m pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/"
    Write-Host "  Use the cu118 index instead if your CUDA/driver stack requires CUDA 11.8."
  }
}

$providerRequiresReadiness = $Provider.ToLowerInvariant() -notin @("mock", "none", "disabled")
if ($providerRequiresReadiness -and -not $diagnostics.available) {
  if (-not $Json) {
    if ($ocrRequiresGpu) {
      Write-WatcherErrorMessage "GPU OCR is required but not ready. Install PaddleOCR plus a compatible paddlepaddle-gpu wheel, then rerun this check."
    } else {
      Write-WatcherErrorMessage "OCR provider '$Provider' is not ready. Install required OCR packages or use -Provider mock."
    }
  }
  exit 1
}

exit 0
