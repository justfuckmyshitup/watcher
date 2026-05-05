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
$repoRoot = Get-LSRepoRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = Get-LSCommand @("python.exe", "python")
}
if (-not $python) {
  Write-LSErrorMessage "Python was not found. Create .venv or install Python, then rerun this script."
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

Write-LSStatus "Running POC benchmark..."
Write-LSStatus "OCR: $OcrProvider / $OcrProfile"
Write-LSStatus "LLM: $ModelProvider"
Write-LSStatus "Iterations: $Iterations"
if ($RequireGpu) {
  Write-LSStatus "GPU proof required."
}

& $python @args
exit $LASTEXITCODE
