[CmdletBinding()]
param(
  [string]$OcrProvider = "paddle",
  [string]$OcrProfile = "screen-fast",
  [string]$ModelProvider = "onnx-phi",
  [switch]$RequireGpu,
  [switch]$SkipOcr,
  [switch]$SkipLlm,
  [switch]$KeepSession
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-WatcherRepoRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  Write-WatcherErrorMessage ".venv was not found. Run .\scripts\setup-live-poc.ps1 first."
  exit 1
}

if ($RequireGpu) {
  Write-WatcherStatus "Checking GPU providers before real POC smoke..."
  & "$PSScriptRoot\check-gpu.ps1" -RequireGpu -RequireCudaProvider -RequirePaddleGpu
  if ($LASTEXITCODE -ne 0) {
    Write-WatcherErrorMessage "GPU readiness failed. Fix the reported provider issue before running the real POC smoke."
    exit 1
  }
}

if (-not $SkipOcr) {
  Write-WatcherStatus "Checking OCR provider..."
  & "$PSScriptRoot\check-ocr.ps1" -Provider $OcrProvider -Profile $OcrProfile -RequireGpu:$RequireGpu
  if ($LASTEXITCODE -ne 0) {
    Write-WatcherErrorMessage "OCR readiness failed."
    exit 1
  }
}

if (-not $SkipLlm -and $ModelProvider.ToLowerInvariant() -in @("onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx")) {
  Write-WatcherStatus "Checking local model files..."
  & "$PSScriptRoot\check-models.ps1" -Profile poc
  if ($LASTEXITCODE -ne 0) {
    Write-WatcherErrorMessage "Local model files are missing. Run .\scripts\download-models.ps1 -Profile poc."
    exit 1
  }
}

$arguments = @(
  (Join-Path $PSScriptRoot "poc_live_smoke.py"),
  "--ocr-provider", $OcrProvider,
  "--ocr-profile", $OcrProfile,
  "--model-provider", $ModelProvider
)
if ($RequireGpu) { $arguments += "--require-gpu" }
if ($SkipOcr) { $arguments += "--skip-ocr" }
if ($SkipLlm) { $arguments += "--skip-llm" }
if ($KeepSession) { $arguments += "--keep-session" }

Write-WatcherStatus "Running real POC smoke loop..."
& $python $arguments
exit $LASTEXITCODE
