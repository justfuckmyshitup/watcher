[CmdletBinding()]
param(
  [string]$Profile = "poc",
  [string]$Revision = "main",
  [switch]$DryRun,
  [switch]$Force
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-LSRepoRoot
Set-Location $repoRoot

if ($Profile -ne "poc") {
  Write-LSErrorMessage "Unknown model profile '$Profile'. Supported profile: poc."
  exit 1
}

$modelsRoot = Join-Path $repoRoot "models"
$localPath = Join-Path $modelsRoot "llm\microsoft--Phi-4-mini-reasoning-onnx"
$selectedPath = Join-Path $localPath "gpu\gpu-int4-rtn-block-32"
$manifestPath = Join-Path $modelsRoot "manifest.json"
$repoId = "microsoft/Phi-4-mini-reasoning-onnx"
$include = "gpu/*"

Ensure-LSDirectory $modelsRoot
Ensure-LSDirectory (Split-Path -Parent $localPath)

if ((Test-Path -LiteralPath $selectedPath) -and -not $Force -and -not $DryRun) {
  Write-LSStatus "Model path already exists: $selectedPath"
  Write-LSStatus "Use -Force to re-download."
  & "$PSScriptRoot\check-models.ps1" -Profile $Profile
  exit $LASTEXITCODE
}

Write-LSStatus "Preparing Hugging Face model download..."
Write-LSStatus "Repo: $repoId"
Write-LSStatus "Include: $include"
Write-LSStatus "Destination: $localPath"

$hf = Get-LSCommand @("hf.exe", "hf")
if ($hf) {
  $args = @("download", $repoId, "--revision", $Revision, "--include", $include, "--local-dir", $localPath)
  if ($DryRun) {
    $args += "--dry-run"
  }
  Write-LSStatus "Using Hugging Face hf CLI..."
  & $hf @args
  if ($LASTEXITCODE -ne 0) {
    Write-LSErrorMessage "hf download failed."
    exit $LASTEXITCODE
  }
} else {
  $python = Join-Path $repoRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $python)) {
    $python = Get-LSCommand @("python.exe", "python")
  }
  if (-not $python) {
    Write-LSErrorMessage "Neither hf CLI nor Python was found. Install Hugging Face CLI or create .venv first."
    exit 1
  }
  if ($DryRun) {
    Write-LSWarn "hf CLI is not installed, so -DryRun cannot query remote files through hf."
    Write-Host "Install with: python -m pip install -U huggingface_hub[hf_xet]"
    exit 0
  }
  $code = @'
import sys
from pathlib import Path

try:
    from huggingface_hub import snapshot_download
except Exception as exc:
    print("huggingface_hub is not installed. Install with: python -m pip install -U huggingface_hub[hf_xet]", file=sys.stderr)
    raise SystemExit(2) from exc

repo_id = sys.argv[1]
revision = sys.argv[2]
include = sys.argv[3]
local_dir = Path(sys.argv[4])
local_dir.mkdir(parents=True, exist_ok=True)
snapshot_download(
    repo_id=repo_id,
    revision=revision,
    allow_patterns=[include],
    local_dir=str(local_dir),
    local_dir_use_symlinks=False,
)
'@
  $probeDir = Join-Path $repoRoot "app-data\tmp\model-download"
  Ensure-LSDirectory $probeDir
  $scriptPath = Join-Path $probeDir "hf-download-$([guid]::NewGuid().ToString('N')).py"
  try {
    $code | Set-Content -LiteralPath $scriptPath -Encoding UTF8
    Write-LSStatus "Using huggingface_hub.snapshot_download fallback..."
    & $python $scriptPath $repoId $Revision $include $localPath
    if ($LASTEXITCODE -ne 0) {
      Write-LSErrorMessage "huggingface_hub download failed."
      exit $LASTEXITCODE
    }
  } finally {
    if (Test-Path -LiteralPath $scriptPath) {
      Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
    }
  }
}

if ($DryRun) {
  exit 0
}

$fileItems = @()
if (Test-Path -LiteralPath $selectedPath) {
  $fileItems = @(Get-ChildItem -Recurse -File -LiteralPath $selectedPath -ErrorAction SilentlyContinue)
}
$manifest = [ordered]@{
  version = 1
  updated_at = (Get-Date).ToString("o")
  models = [ordered]@{
    "phi4-mini-reasoning-onnx" = [ordered]@{
      key = "phi4-mini-reasoning-onnx"
      repo_id = $repoId
      revision = $Revision
      license = "MIT"
      provider = "onnxruntime-genai-cuda"
      include = @($include)
      local_path = $localPath
      selected_path = $selectedPath
      downloaded_at = (Get-Date).ToString("o")
      file_count = $fileItems.Count
      bytes = [int64](($fileItems | Measure-Object -Property Length -Sum).Sum)
    }
  }
}

($manifest | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-LSStatus "Wrote model manifest: $manifestPath"
& "$PSScriptRoot\check-models.ps1" -Profile $Profile
exit $LASTEXITCODE
