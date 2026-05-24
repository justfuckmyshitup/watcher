[CmdletBinding()]
param(
  [int]$BackendPort = 8765,
  [int]$VitePort = 5173,
  [switch]$DockerBackend,
  [switch]$NoPortCheck,
  [switch]$InstallSystemDeps,
  [switch]$RequireGpu,
  [switch]$AllowCpuFallback,
  [string]$OcrProvider = "",
  [string]$OcrProfile = "screen-fast",
  [string]$ModelProvider = "",
  [string]$ModelProfile = "poc"
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-WatcherRepoRoot
Set-Location $repoRoot

$missing = @()

Write-WatcherStatus "Checking Python..."
$python = Get-WatcherCommand @("python.exe", "python")
if ($python) {
  Write-WatcherStatus "Python found: $python"
} else {
  $missing += "Python"
  Write-WatcherErrorMessage "Python was not found. Install Python 3.12+ from https://www.python.org/downloads/ and rerun this script."
  Write-Host "Optional winget command: winget install Python.Python.3.12"
}

Write-WatcherStatus "Checking Node/npm..."
$node = Get-WatcherCommand @("node.exe", "node")
$npm = Get-WatcherCommand @("npm.cmd", "npm")
if ($node) {
  Write-WatcherStatus "Node.js found: $node"
} else {
  $missing += "Node.js"
  Write-WatcherErrorMessage "Node.js was not found. Install Node.js LTS from https://nodejs.org/ and rerun this script."
  Write-Host "Optional winget command: winget install OpenJS.NodeJS.LTS"
}
if ($npm) {
  Write-WatcherStatus "npm found: $npm"
} else {
  $missing += "npm"
  Write-WatcherErrorMessage "npm was not found. Reinstall Node.js LTS with npm enabled."
}

if ($DockerBackend) {
  Write-WatcherStatus "Checking Docker..."
  $docker = Get-WatcherCommand @("docker.exe", "docker")
  if (-not $docker) {
    $missing += "Docker"
    Write-WatcherErrorMessage "Docker was not found. Install Docker Desktop, start it, then rerun with -DockerBackend."
    Write-Host "Optional winget command: winget install Docker.DockerDesktop"
  } else {
    try {
      & $docker version | Out-Null
      Write-WatcherStatus "Docker is installed and running."
    } catch {
      $missing += "Docker running"
      Write-WatcherErrorMessage "Docker is installed but does not appear to be running. Start Docker Desktop and rerun."
    }
  }
}

if ($RequireGpu -and -not $AllowCpuFallback) {
  Write-WatcherStatus "Checking GPU acceleration..."
  & "$PSScriptRoot\check-gpu.ps1" -RequireGpu -SkipPackageProbe
  if ($LASTEXITCODE -ne 0) {
    $missing += "NVIDIA GPU"
  }
} elseif ($AllowCpuFallback) {
  Write-WatcherWarn "CPU fallback explicitly allowed. GPU checks are advisory only."
  & "$PSScriptRoot\check-gpu.ps1" -SkipPackageProbe
}

if (-not [string]::IsNullOrWhiteSpace($OcrProvider)) {
  Write-WatcherStatus "Checking OCR provider..."
  & "$PSScriptRoot\check-ocr.ps1" -Provider $OcrProvider -Profile $OcrProfile -RequireGpu:$RequireGpu -AllowCpuFallback:$AllowCpuFallback
  if ($LASTEXITCODE -ne 0) {
    $missing += "OCR provider $OcrProvider"
  }
}

$providerToCheck = $ModelProvider
if ([string]::IsNullOrWhiteSpace($providerToCheck)) {
  $providerToCheck = [string]$env:WATCHER_PROVIDER
}
$providerRequiresGpu = -not [string]::IsNullOrWhiteSpace($providerToCheck) -and $providerToCheck.ToLowerInvariant() -notin @("mock")
if ($providerRequiresGpu -and -not $AllowCpuFallback -and -not $RequireGpu) {
  Write-WatcherStatus "Checking GPU acceleration for model provider '$providerToCheck'..."
  & "$PSScriptRoot\check-gpu.ps1" -RequireGpu -SkipPackageProbe
  if ($LASTEXITCODE -ne 0) {
    $missing += "NVIDIA GPU"
  }
}
if (-not [string]::IsNullOrWhiteSpace($providerToCheck) -and $providerToCheck.ToLowerInvariant() -in @("onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx")) {
  Write-WatcherStatus "Checking local model files..."
  & "$PSScriptRoot\check-models.ps1" -Profile $ModelProfile
  if ($LASTEXITCODE -ne 0) {
    $missing += "Local ONNX model files"
  }
}

if (-not $NoPortCheck) {
  Write-WatcherStatus "Checking backend port $BackendPort..."
  if (Test-WatcherPortOpen $BackendPort) {
    $health = Invoke-WatcherHealthCheck -BackendPort $BackendPort
    if ($health -and $health.app -eq "Watcher") {
      Write-WatcherWarn "Port $BackendPort is already serving Watcher."
    } else {
      $owner = Get-WatcherPortOwner -Port $BackendPort
      if ($owner) { $ownerText = "PID $owner" } else { $ownerText = "an unknown process" }
      Write-WatcherErrorMessage "Port $BackendPort is already in use by $ownerText. Stop that process or choose -BackendPort."
      $missing += "Backend port free"
    }
  } else {
    Write-WatcherStatus "Backend port $BackendPort is free."
  }

  Write-WatcherStatus "Checking Vite port $VitePort..."
  if (Test-WatcherPortOpen $VitePort) {
    $owner = Get-WatcherPortOwner -Port $VitePort
    if ($owner) { $ownerText = "PID $owner" } else { $ownerText = "an unknown process" }
    Write-WatcherErrorMessage "Port $VitePort is already in use by $ownerText. Stop that process or choose -VitePort."
    $missing += "Vite port free"
  } else {
    Write-WatcherStatus "Vite port $VitePort is free."
  }
}

if ($InstallSystemDeps -and $missing.Count -gt 0) {
  Write-WatcherWarn "-InstallSystemDeps is intentionally conservative. No system dependencies were installed automatically."
  Write-Host "Run the displayed winget command(s) yourself, then rerun this script."
}

if ($missing.Count -gt 0) {
  Write-WatcherErrorMessage "Dependency check failed: $($missing -join ', ')"
  exit 1
}

Write-WatcherStatus "Dependency check passed."
exit 0
