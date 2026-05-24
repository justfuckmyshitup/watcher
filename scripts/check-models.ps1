[CmdletBinding()]
param(
  [string]$Profile = "poc",
  [switch]$Json
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-WatcherRepoRoot
Set-Location $repoRoot

if ($Profile -ne "poc") {
  Write-WatcherErrorMessage "Unknown model profile '$Profile'. Supported profile: poc."
  exit 1
}

$modelsRoot = Join-Path $repoRoot "models"
$manifestPath = Join-Path $modelsRoot "manifest.json"
$localPath = Join-Path $modelsRoot "llm\microsoft--Phi-4-mini-reasoning-onnx"
$selectedPath = Join-Path $localPath "gpu\gpu-int4-rtn-block-32"
$configPath = Join-Path $selectedPath "genai_config.json"
$altConfigPath = Join-Path $selectedPath "config.json"
$manifest = $null

if (Test-Path -LiteralPath $manifestPath) {
  try {
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
  } catch {
    $manifest = $null
  }
}

$ready = (Test-Path -LiteralPath $selectedPath) -and ((Test-Path -LiteralPath $configPath) -or (Test-Path -LiteralPath $altConfigPath))
$files = 0
$bytes = 0
if (Test-Path -LiteralPath $selectedPath) {
  $fileItems = Get-ChildItem -Recurse -File -LiteralPath $selectedPath -ErrorAction SilentlyContinue
  $files = ($fileItems | Measure-Object).Count
  $bytes = ($fileItems | Measure-Object -Property Length -Sum).Sum
}

$report = [ordered]@{
  profile = $Profile
  ready = $ready
  repo_id = "microsoft/Phi-4-mini-reasoning-onnx"
  model_key = "phi4-mini-reasoning-onnx"
  provider = "onnxruntime-genai-cuda"
  local_path = $localPath
  selected_path = $selectedPath
  manifest_path = $manifestPath
  manifest_present = [bool]$manifest
  file_count = $files
  bytes = [int64]$bytes
  requires_download = -not $ready
}

if ($Json) {
  $report | ConvertTo-Json -Depth 8
} else {
  Write-WatcherStatus "Checking local model profile '$Profile'..."
  Write-WatcherStatus "Model: microsoft/Phi-4-mini-reasoning-onnx"
  Write-WatcherStatus "Selected path: $selectedPath"
  if ($ready) {
    Write-WatcherStatus "Model files are present."
  } else {
    Write-WatcherWarn "Model files are missing or incomplete."
    Write-Host "Run: .\scripts\download-models.ps1 -Profile poc"
  }
}

if (-not $ready) {
  exit 1
}
exit 0
