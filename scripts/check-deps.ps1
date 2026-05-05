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
$repoRoot = Get-LSRepoRoot
Set-Location $repoRoot

$missing = @()

Write-LSStatus "Checking Python..."
$python = Get-LSCommand @("python.exe", "python")
if ($python) {
  Write-LSStatus "Python found: $python"
} else {
  $missing += "Python"
  Write-LSErrorMessage "Python was not found. Install Python 3.12+ from https://www.python.org/downloads/ and rerun this script."
  Write-Host "Optional winget command: winget install Python.Python.3.12"
}

Write-LSStatus "Checking Node/npm..."
$node = Get-LSCommand @("node.exe", "node")
$npm = Get-LSCommand @("npm.cmd", "npm")
if ($node) {
  Write-LSStatus "Node.js found: $node"
} else {
  $missing += "Node.js"
  Write-LSErrorMessage "Node.js was not found. Install Node.js LTS from https://nodejs.org/ and rerun this script."
  Write-Host "Optional winget command: winget install OpenJS.NodeJS.LTS"
}
if ($npm) {
  Write-LSStatus "npm found: $npm"
} else {
  $missing += "npm"
  Write-LSErrorMessage "npm was not found. Reinstall Node.js LTS with npm enabled."
}

if ($DockerBackend) {
  Write-LSStatus "Checking Docker..."
  $docker = Get-LSCommand @("docker.exe", "docker")
  if (-not $docker) {
    $missing += "Docker"
    Write-LSErrorMessage "Docker was not found. Install Docker Desktop, start it, then rerun with -DockerBackend."
    Write-Host "Optional winget command: winget install Docker.DockerDesktop"
  } else {
    try {
      & $docker version | Out-Null
      Write-LSStatus "Docker is installed and running."
    } catch {
      $missing += "Docker running"
      Write-LSErrorMessage "Docker is installed but does not appear to be running. Start Docker Desktop and rerun."
    }
  }
}

if ($RequireGpu -and -not $AllowCpuFallback) {
  Write-LSStatus "Checking GPU acceleration..."
  & "$PSScriptRoot\check-gpu.ps1" -RequireGpu -SkipPackageProbe
  if ($LASTEXITCODE -ne 0) {
    $missing += "NVIDIA GPU"
  }
} elseif ($AllowCpuFallback) {
  Write-LSWarn "CPU fallback explicitly allowed. GPU checks are advisory only."
  & "$PSScriptRoot\check-gpu.ps1" -SkipPackageProbe
}

if (-not [string]::IsNullOrWhiteSpace($OcrProvider)) {
  Write-LSStatus "Checking OCR provider..."
  & "$PSScriptRoot\check-ocr.ps1" -Provider $OcrProvider -Profile $OcrProfile -RequireGpu:$RequireGpu -AllowCpuFallback:$AllowCpuFallback
  if ($LASTEXITCODE -ne 0) {
    $missing += "OCR provider $OcrProvider"
  }
}

$providerToCheck = $ModelProvider
if ([string]::IsNullOrWhiteSpace($providerToCheck)) {
  $providerToCheck = [string]$env:LOCAL_SCRIBE_PROVIDER
}
$providerRequiresGpu = -not [string]::IsNullOrWhiteSpace($providerToCheck) -and $providerToCheck.ToLowerInvariant() -notin @("mock")
if ($providerRequiresGpu -and -not $AllowCpuFallback -and -not $RequireGpu) {
  Write-LSStatus "Checking GPU acceleration for model provider '$providerToCheck'..."
  & "$PSScriptRoot\check-gpu.ps1" -RequireGpu -SkipPackageProbe
  if ($LASTEXITCODE -ne 0) {
    $missing += "NVIDIA GPU"
  }
}
if (-not [string]::IsNullOrWhiteSpace($providerToCheck) -and $providerToCheck.ToLowerInvariant() -in @("onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx")) {
  Write-LSStatus "Checking local model files..."
  & "$PSScriptRoot\check-models.ps1" -Profile $ModelProfile
  if ($LASTEXITCODE -ne 0) {
    $missing += "Local ONNX model files"
  }
}

if (-not $NoPortCheck) {
  Write-LSStatus "Checking backend port $BackendPort..."
  if (Test-LSPortOpen $BackendPort) {
    $health = Invoke-LSHealthCheck -BackendPort $BackendPort
    if ($health -and $health.app -eq "Local Scribe") {
      Write-LSWarn "Port $BackendPort is already serving Local Scribe."
    } else {
      $owner = Get-LSPortOwner -Port $BackendPort
      if ($owner) { $ownerText = "PID $owner" } else { $ownerText = "an unknown process" }
      Write-LSErrorMessage "Port $BackendPort is already in use by $ownerText. Stop that process or choose -BackendPort."
      $missing += "Backend port free"
    }
  } else {
    Write-LSStatus "Backend port $BackendPort is free."
  }

  Write-LSStatus "Checking Vite port $VitePort..."
  if (Test-LSPortOpen $VitePort) {
    $owner = Get-LSPortOwner -Port $VitePort
    if ($owner) { $ownerText = "PID $owner" } else { $ownerText = "an unknown process" }
    Write-LSErrorMessage "Port $VitePort is already in use by $ownerText. Stop that process or choose -VitePort."
    $missing += "Vite port free"
  } else {
    Write-LSStatus "Vite port $VitePort is free."
  }
}

if ($InstallSystemDeps -and $missing.Count -gt 0) {
  Write-LSWarn "-InstallSystemDeps is intentionally conservative. No system dependencies were installed automatically."
  Write-Host "Run the displayed winget command(s) yourself, then rerun this script."
}

if ($missing.Count -gt 0) {
  Write-LSErrorMessage "Dependency check failed: $($missing -join ', ')"
  exit 1
}

Write-LSStatus "Dependency check passed."
exit 0
