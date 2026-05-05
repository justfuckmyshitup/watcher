[CmdletBinding()]
param(
  [int]$BackendPort = 8765,
  [int]$VitePort = 5173,
  [switch]$NoInstall,
  [switch]$SkipNpmInstall,
  [switch]$SkipPipInstall,
  [switch]$Mock,
  [switch]$DockerBackend,
  [switch]$InstallSystemDeps,
  [switch]$ForceStopStale,
  [switch]$NoLaunch,
  [switch]$NoPrompt,
  [switch]$RequireGpu,
  [switch]$AllowCpuFallback,
  [string]$OcrProvider = "",
  [string]$OcrProfile = "screen-fast",
  [string]$ModelProvider = "",
  [string]$ModelProfile = "poc",
  [switch]$SkipModelCheck
)

$launcher = Join-Path $PSScriptRoot "scripts\start-localscribe.ps1"
& $launcher @PSBoundParameters
exit $LASTEXITCODE
