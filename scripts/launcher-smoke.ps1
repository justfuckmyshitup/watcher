[CmdletBinding()]
param(
  [int]$BackendPort = 8765,
  [int]$VitePort = 5174,
  [switch]$DockerBackend,
  [switch]$RequireGpu,
  [string]$OcrProvider = "",
  [string]$OcrProfile = "screen-fast",
  [string]$ModelProvider = "",
  [string]$ModelProfile = "poc"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$start = Join-Path $root "start.ps1"
$check = Join-Path $PSScriptRoot "check-deps.ps1"

Write-Host "[Local Scribe] Launcher smoke: dependency check..."
if ($DockerBackend) {
  & $check -BackendPort $BackendPort -VitePort $VitePort -DockerBackend -NoPortCheck -RequireGpu:$RequireGpu -OcrProvider $OcrProvider -OcrProfile $OcrProfile -ModelProvider $ModelProvider -ModelProfile $ModelProfile
} else {
  & $check -BackendPort $BackendPort -VitePort $VitePort -NoPortCheck -RequireGpu:$RequireGpu -OcrProvider $OcrProvider -OcrProfile $OcrProfile -ModelProvider $ModelProvider -ModelProfile $ModelProfile
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[Local Scribe] Launcher smoke: backend/Vite startup and Electron command verification..."
if ($DockerBackend) {
  & $start -BackendPort $BackendPort -VitePort $VitePort -DockerBackend -NoLaunch -ForceStopStale -RequireGpu:$RequireGpu -OcrProvider $OcrProvider -OcrProfile $OcrProfile
} else {
  & $start -BackendPort $BackendPort -VitePort $VitePort -Mock -NoLaunch -ForceStopStale -RequireGpu:$RequireGpu -OcrProvider $OcrProvider -OcrProfile $OcrProfile
}
exit $LASTEXITCODE
