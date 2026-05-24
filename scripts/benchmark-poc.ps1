[CmdletBinding()]
param(
  [string]$OcrProvider = "mock",
  [string]$OcrProfile = "screen-fast",
  [string]$ModelProvider = "mock",
  [int]$Iterations = 3,
  [switch]$RequireGpu,
  [switch]$Offline,
  [switch]$SkipOcr,
  [switch]$SkipLlm,
  [switch]$AllowIncomplete,
  [switch]$Json,
  [string]$OutputDir = ""
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-WatcherRepoRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = Get-WatcherCommand @("python.exe", "python")
}
if (-not $python) {
  Write-WatcherErrorMessage "Python was not found. Create .venv or install Python, then rerun this script."
  exit 1
}

$args = @(
  (Join-Path $repoRoot "scripts\benchmark_poc.py"),
  "--ocr-provider", $OcrProvider,
  "--ocr-profile", $OcrProfile,
  "--model-provider", $ModelProvider,
  "--iterations", [string]$Iterations
)
if ($RequireGpu) { $args += "--require-gpu" }
if ($Offline) { $args += "--offline" }
if ($SkipOcr) { $args += "--skip-ocr" }
if ($SkipLlm) { $args += "--skip-llm" }
if ($AllowIncomplete) { $args += "--allow-incomplete" }
if ($Json) { $args += "--json" }
if (-not [string]::IsNullOrWhiteSpace($OutputDir)) {
  $args += @("--output-dir", $OutputDir)
}

Write-WatcherStatus "Running POC benchmark..."
Write-WatcherStatus "OCR: $OcrProvider / $OcrProfile"
Write-WatcherStatus "LLM: $ModelProvider"
Write-WatcherStatus "Iterations: $Iterations"
if ($RequireGpu) {
  Write-WatcherStatus "GPU proof required."
}

& $python @args
exit $LASTEXITCODE
