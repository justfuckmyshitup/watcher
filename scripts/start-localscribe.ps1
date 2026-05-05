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

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-LSRepoRoot
$exitCode = 0
$debugMode = $PSBoundParameters.ContainsKey("Debug") -or $DebugPreference -ne "SilentlyContinue"
$script:UserProvidedVitePort = $PSBoundParameters.ContainsKey("VitePort")
$state = @{
  RepoRoot = $repoRoot
  BackendPort = $BackendPort
  VitePort = $VitePort
  BackendPid = $null
  VitePid = $null
  ElectronPid = $null
  DockerBackend = [bool]$DockerBackend
  RequireGpu = [bool]$RequireGpu
  AllowCpuFallback = [bool]$AllowCpuFallback
  OcrProvider = $OcrProvider
  OcrProfile = $OcrProfile
  ModelProvider = $ModelProvider
  ModelProfile = $ModelProfile
  StartedAt = (Get-Date).ToString("o")
}

function Fail-Launcher {
  param([string]$Message)
  throw $Message
}

function Read-LauncherChoice {
  param(
    [string]$Prompt,
    [string[]]$Options,
    [string]$Default = "1"
  )
  Write-Host ""
  Write-Host "$script:LocalScribePrefix $Prompt"
  for ($index = 0; $index -lt $Options.Count; $index += 1) {
    Write-Host ("  {0}. {1}" -f ($index + 1), $Options[$index])
  }
  $choice = Read-Host "Choose [$Default]"
  if ([string]::IsNullOrWhiteSpace($choice)) {
    $choice = $Default
  }
  if ($choice -notmatch '^\d+$') {
    Write-LSWarn "Invalid choice '$choice'. Using option $Default."
    return [int]$Default
  }
  $number = [int]$choice
  if ($number -lt 1 -or $number -gt $Options.Count) {
    Write-LSWarn "Choice '$choice' is out of range. Using option $Default."
    return [int]$Default
  }
  return $number
}

function Invoke-LauncherInteractiveMenu {
  if ($NoPrompt -or $PSBoundParameters.Count -gt 0) {
    return
  }

  Write-Host ""
  Write-Host "$script:LocalScribePrefix Interactive launcher"
  Write-Host "$script:LocalScribePrefix Press Enter to accept the recommended option."

  $environment = Read-LauncherChoice `
    -Prompt "Environment" `
    -Options @(
      "Native Windows runtime (recommended)",
      "Docker backend"
    )
  if ($environment -eq 2) {
    $script:DockerBackend = $true
    $state.DockerBackend = [bool]$DockerBackend
  }

  $hardware = Read-LauncherChoice `
    -Prompt "Hardware policy" `
    -Options @(
      "Require NVIDIA GPU acceleration (recommended)",
      "Allow explicit CPU fallback"
    )
  if ($hardware -eq 1) {
    $script:RequireGpu = $true
    $script:AllowCpuFallback = $false
  } else {
    $script:AllowCpuFallback = $true
    $script:RequireGpu = $false
  }

  $model = Read-LauncherChoice `
    -Prompt "Local model provider" `
    -Options @(
      "Microsoft Phi-4 mini reasoning ONNX from local Hugging Face cache (recommended)",
      "Ollama on localhost",
      "LM Studio on localhost"
    )
  if ($model -eq 1) {
    $script:ModelProvider = "onnx-phi"
  } elseif ($model -eq 2) {
    $script:ModelProvider = "ollama"
  } else {
    $script:ModelProvider = "lmstudio"
  }

  $ocr = Read-LauncherChoice `
    -Prompt "OCR provider" `
    -Options @(
      "PaddleOCR screen-fast on GPU (recommended)",
      "PaddleOCR screen-accurate on GPU"
    )
  if ($ocr -eq 1) {
    $script:OcrProvider = "paddle"
    $script:OcrProfile = "screen-fast"
  } else {
    $script:OcrProvider = "paddle"
    $script:OcrProfile = "screen-accurate"
  }

  $state.DockerBackend = [bool]$DockerBackend
  $state.RequireGpu = [bool]$RequireGpu
  $state.AllowCpuFallback = [bool]$AllowCpuFallback
  $state.OcrProvider = $OcrProvider
  $state.OcrProfile = $OcrProfile
  $state.ModelProvider = $ModelProvider
}

function Get-LauncherFreeVitePort {
  for ($candidate = 5174; $candidate -le 5199; $candidate += 1) {
    if (-not (Test-LSPortOpen -Port $candidate)) {
      return $candidate
    }
  }
  return $null
}

function Resolve-LauncherPortConflict {
  param(
    [int]$Port,
    [string]$ServiceName
  )
  if (-not (Test-LSPortOpen -Port $Port)) {
    return
  }

  $owner = Get-LSPortOwner -Port $Port
  $stateOnDisk = Read-LSState -RepoRoot $repoRoot
  $knownPid = $null
  if ($stateOnDisk) {
    if ($ServiceName -eq "backend" -and $stateOnDisk.BackendPid) { $knownPid = [int]$stateOnDisk.BackendPid }
    if ($ServiceName -eq "vite" -and $stateOnDisk.VitePid) { $knownPid = [int]$stateOnDisk.VitePid }
  }

  $appearsLocalScribe = $false
  if ($ServiceName -eq "backend") {
    $health = Invoke-LSHealthCheck -BackendPort $Port
    if ($health -and $health.app -eq "Local Scribe") {
      $appearsLocalScribe = $true
    }
  } elseif ($owner) {
    $cmdLine = Get-LSProcessCommandLine -ProcessId $owner
    if ($cmdLine -match "vite" -and $cmdLine -match [regex]::Escape($repoRoot)) {
      $appearsLocalScribe = $true
    }
  }

  if ($knownPid -and (Test-LSProcessRunning -ProcessId $knownPid)) {
    if (Confirm-LSAction -Prompt "$ServiceName port $Port is occupied by a previous Local Scribe launcher process. Stop it now?" -AssumeYes:$ForceStopStale) {
      & "$PSScriptRoot\stop-localscribe.ps1" -Quiet
      Start-Sleep -Seconds 2
      if (-not (Test-LSPortOpen -Port $Port)) { return }
    }
    Fail-Launcher "$ServiceName port $Port is still occupied. Close the old Local Scribe process or rerun with -ForceStopStale."
  }

  if ($appearsLocalScribe -and $owner) {
    if (Confirm-LSAction -Prompt "$ServiceName port $Port appears to be a stale Local Scribe process (PID $owner). Stop it now?" -AssumeYes:$ForceStopStale) {
      Stop-LSProcessTree -ProcessId $owner -Name "stale $ServiceName"
      Start-Sleep -Seconds 2
      if (-not (Test-LSPortOpen -Port $Port)) { return }
    }
    Fail-Launcher "$ServiceName port $Port is still occupied by Local Scribe. Stop PID $owner or choose another port."
  }

  if ($owner) { $ownerText = "PID $owner" } else { $ownerText = "an unknown process" }
  if ($ServiceName -eq "vite" -and -not $script:UserProvidedVitePort) {
    $alternatePort = Get-LauncherFreeVitePort
    if ($alternatePort) {
      Write-LSWarn "vite port $Port is already in use by $ownerText. Using http://127.0.0.1:$alternatePort instead."
      $script:VitePort = [int]$alternatePort
      $state.VitePort = [int]$alternatePort
      return
    }
  }
  Fail-Launcher "$ServiceName port $Port is already in use by $ownerText and does not appear to be Local Scribe. Stop that process or rerun with a different port."
}

function Ensure-SystemDeps {
  Write-LSStatus "Checking Python..."
  $script:SystemPython = Get-LSCommand @("python.exe", "python")
  if (-not $script:SystemPython -and -not $DockerBackend) {
    Write-Host "Optional install command: winget install Python.Python.3.12"
    Fail-Launcher "Python was not found. Please install Python 3.12+ from https://www.python.org/downloads/ and rerun this script."
  }
  if ($script:SystemPython) { Write-LSStatus "Python found." }

  Write-LSStatus "Checking Node/npm..."
  $script:NodeCommand = Get-LSCommand @("node.exe", "node")
  $script:NpmCommand = Get-LSCommand @("npm.cmd", "npm")
  if (-not $script:NodeCommand) {
    Write-Host "Optional install command: winget install OpenJS.NodeJS.LTS"
    Fail-Launcher "Node.js was not found. Please install Node.js LTS from https://nodejs.org/ and rerun this script."
  }
  if (-not $script:NpmCommand) {
    Fail-Launcher "npm was not found. Reinstall Node.js LTS with npm enabled, then rerun this script."
  }
  Write-LSStatus "Node/npm found."

  if ($DockerBackend) {
    Write-LSStatus "Checking Docker..."
    $script:DockerCommand = Get-LSCommand @("docker.exe", "docker")
    if (-not $script:DockerCommand) {
      Write-Host "Optional install command: winget install Docker.DockerDesktop"
      Fail-Launcher "Docker was not found. Install Docker Desktop, start it, then rerun with -DockerBackend."
    }
    try {
      & $script:DockerCommand version | Out-Null
      Write-LSStatus "Docker is installed and running."
    } catch {
      Fail-Launcher "Docker is installed but not running. Start Docker Desktop, then rerun with -DockerBackend."
    }
  }

  if ($InstallSystemDeps) {
    Write-LSWarn "-InstallSystemDeps does not silently install system tools. Use the displayed winget commands only after reviewing them."
  }
}

function Test-LauncherRequiresGpu {
  if ($AllowCpuFallback) {
    return $false
  }
  if ($RequireGpu) {
    return $true
  }
  if ($Mock) {
    return $false
  }
  $provider = [string]$env:LOCAL_SCRIBE_PROVIDER
  if ([string]::IsNullOrWhiteSpace($provider)) {
    return $false
  }
  return $provider.ToLowerInvariant() -notin @("mock")
}

function Initialize-LauncherModelProvider {
  if ($Mock) {
    $env:LOCAL_SCRIBE_PROVIDER = "mock"
    $state.ModelProvider = "mock"
    return
  }
  if (-not [string]::IsNullOrWhiteSpace($ModelProvider)) {
    $env:LOCAL_SCRIBE_PROVIDER = $ModelProvider
    $state.ModelProvider = $ModelProvider
    return
  }
  if ([string]::IsNullOrWhiteSpace([string]$env:LOCAL_SCRIBE_PROVIDER)) {
    $env:LOCAL_SCRIBE_PROVIDER = "onnx-phi"
    $state.ModelProvider = "onnx-phi"
    Write-LSStatus "Defaulting to live local LLM provider: onnx-phi"
  } else {
    $state.ModelProvider = [string]$env:LOCAL_SCRIBE_PROVIDER
  }
}

function Resolve-LauncherOcrProvider {
  $provider = $OcrProvider
  if ([string]::IsNullOrWhiteSpace($provider)) {
    $provider = [string]$env:LOCAL_SCRIBE_OCR_PROVIDER
  }
  if ([string]::IsNullOrWhiteSpace($provider)) {
    if ($Mock -or $DockerBackend) {
      $provider = "mock"
    } else {
      $provider = "paddle"
      Write-LSStatus "Defaulting to live OCR provider: paddle"
    }
    $env:LOCAL_SCRIBE_OCR_PROVIDER = $provider
    $state.OcrProvider = $provider
  }
  return $provider
}

function Test-LauncherUsesLivePocRuntime {
  if ($Mock -or $DockerBackend) {
    return $false
  }
  $model = [string]$env:LOCAL_SCRIBE_PROVIDER
  $ocr = Resolve-LauncherOcrProvider
  return ($model.ToLowerInvariant() -in @("onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx")) -or ($ocr.ToLowerInvariant() -in @("paddle", "paddleocr"))
}

function Invoke-LauncherGpuGate {
  $gpuRequired = Test-LauncherRequiresGpu
  if ($AllowCpuFallback) {
    Write-LSWarn "CPU fallback explicitly allowed. Live OCR/LLM performance may be poor if providers miss the GPU."
    $env:LOCAL_SCRIBE_REQUIRE_GPU = "false"
    return
  }
  if (-not $gpuRequired) {
    $env:LOCAL_SCRIBE_REQUIRE_GPU = "false"
    return
  }

  Write-LSStatus "Checking GPU acceleration gate..."
  & "$PSScriptRoot\check-gpu.ps1" -RequireGpu -SkipPackageProbe
  if ($LASTEXITCODE -ne 0) {
    Fail-Launcher "GPU acceleration is required for this launch, but the NVIDIA GPU gate failed. Rerun .\scripts\check-gpu.ps1 for details, or rerun with -AllowCpuFallback only if you accept slow CPU/system RAM execution."
  }
  $env:LOCAL_SCRIBE_REQUIRE_GPU = "true"
  $state.RequireGpu = $true
}

function Invoke-LauncherOcrGate {
  $provider = Resolve-LauncherOcrProvider
  $env:LOCAL_SCRIBE_OCR_PROVIDER = $provider
  $env:LOCAL_SCRIBE_OCR_PROFILE = $OcrProfile

  if ($provider.ToLowerInvariant() -in @("mock", "none", "disabled")) {
    $env:LOCAL_SCRIBE_OCR_REQUIRE_GPU = "false"
    return
  }

  $gpuRequired = Test-LauncherRequiresGpu
  if ($AllowCpuFallback) {
    $env:LOCAL_SCRIBE_OCR_REQUIRE_GPU = "false"
    Write-LSWarn "OCR CPU fallback explicitly allowed. PaddleOCR may run slowly if GPU packages are missing."
  } elseif ($gpuRequired) {
    $env:LOCAL_SCRIBE_OCR_REQUIRE_GPU = "true"
  }

  Write-LSStatus "Checking OCR provider..."
  & "$PSScriptRoot\check-ocr.ps1" -Provider $provider -Profile $OcrProfile -RequireGpu:$gpuRequired -AllowCpuFallback:$AllowCpuFallback
  if ($LASTEXITCODE -ne 0) {
    Fail-Launcher "OCR provider '$provider' is not ready. Rerun .\scripts\check-ocr.ps1 -Provider $provider -RequireGpu for details."
  }
}

function Test-LauncherUsesLocalOnnxModel {
  $provider = [string]$env:LOCAL_SCRIBE_PROVIDER
  if ([string]::IsNullOrWhiteSpace($provider)) {
    return $false
  }
  return $provider.ToLowerInvariant() -in @("onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx")
}

function Invoke-LauncherModelGate {
  if (-not (Test-LauncherUsesLocalOnnxModel)) {
    return
  }
  $env:HF_HUB_OFFLINE = "1"
  $env:TRANSFORMERS_OFFLINE = "1"
  if ($SkipModelCheck) {
    Write-LSWarn "Skipping local model check even though LOCAL_SCRIBE_PROVIDER requests ONNX Phi."
    return
  }
  Write-LSStatus "Checking local model files..."
  & "$PSScriptRoot\check-models.ps1" -Profile $ModelProfile
  if ($LASTEXITCODE -ne 0) {
    Fail-Launcher "Local ONNX model files are missing. Run .\scripts\download-models.ps1 -Profile $ModelProfile, then rerun the launcher."
  }
}

function Test-LauncherLivePocReady {
  if (-not (Test-LauncherUsesLivePocRuntime)) {
    return $true
  }
  $ready = $true
  if (Test-LauncherUsesLocalOnnxModel) {
    & "$PSScriptRoot\check-models.ps1" -Profile $ModelProfile *> $null
    if ($LASTEXITCODE -ne 0) { $ready = $false }
  }
  $ocr = Resolve-LauncherOcrProvider
  if ($ocr.ToLowerInvariant() -in @("paddle", "paddleocr")) {
    & "$PSScriptRoot\check-ocr.ps1" -Provider $ocr -Profile $OcrProfile -RequireGpu *> $null
    if ($LASTEXITCODE -ne 0) { $ready = $false }
  }
  return $ready
}

function Ensure-LivePocRuntime {
  if (-not (Test-LauncherUsesLivePocRuntime)) {
    return
  }
  if ($NoInstall) {
    Write-LSWarn "-NoInstall set. Skipping live POC runtime install/download checks."
    return
  }
  if (Test-LauncherLivePocReady) {
    Write-LSStatus "Live POC runtime is ready."
    return
  }

  Write-LSStatus "Installing/downloading live POC runtime packages and model files..."
  & "$PSScriptRoot\setup-live-poc.ps1" -InstallRuntimePackages -DownloadModels
  if ($LASTEXITCODE -ne 0) {
    Fail-Launcher "Live POC setup failed. Check the setup output above, then rerun .\start.ps1."
  }
}

function Ensure-PythonEnv {
  if ($DockerBackend) { return }
  $venvDir = Join-Path $repoRoot ".venv"
  $script:VenvPython = Join-Path $venvDir "Scripts\python.exe"

  if (-not (Test-Path -LiteralPath $script:VenvPython)) {
    if ($NoInstall) {
      Fail-Launcher ".venv is missing and -NoInstall was set. Run without -NoInstall to create the repo-local Python environment."
    }
    Write-LSStatus "Creating virtual environment..."
    Invoke-LSLoggedCommand -FilePath $script:SystemPython `
      -ArgumentList @("-m", "venv", ".venv") `
      -WorkingDirectory $repoRoot `
      -LogPath (Join-Path $script:LogDir "venv-create.log") `
      -FailureMessage "Failed to create .venv."
  } else {
    Write-LSStatus "Using existing .venv."
  }

  $venvPip = Join-Path $venvDir "Scripts\pip.exe"
  $pipReady = Test-Path -LiteralPath $venvPip
  if ($pipReady) {
    & $script:VenvPython -m pip --version *> $null
    $pipReady = ($LASTEXITCODE -eq 0)
  }
  if (-not $pipReady) {
    Write-LSStatus "Bootstrapping pip in .venv..."
    Invoke-LSLoggedCommand -FilePath $script:VenvPython `
      -ArgumentList @("-m", "ensurepip", "--upgrade", "--default-pip") `
      -WorkingDirectory $repoRoot `
      -LogPath (Join-Path $script:LogDir "venv-ensurepip.log") `
      -FailureMessage "Failed to bootstrap pip in .venv."
  }

  $requirements = Join-Path $repoRoot "backend\requirements.txt"
  $marker = Join-Path (Get-LSLauncherDir $repoRoot) "backend-requirements.sha256"
  $currentHash = Get-LSFileHashText @($requirements)
  $installedHash = ""
  if (Test-Path -LiteralPath $marker) { $installedHash = (Get-Content -Raw -LiteralPath $marker).Trim() }

  if (($NoInstall -or $SkipPipInstall) -and $currentHash -ne $installedHash) {
    Write-LSWarn "Skipping backend dependency install even though requirements changed."
    return
  }

  if ($currentHash -ne $installedHash) {
    Write-LSStatus "Installing backend dependencies..."
    Invoke-LSLoggedCommand -FilePath $script:VenvPython `
      -ArgumentList @("-m", "pip", "install", "-r", $requirements) `
      -WorkingDirectory $repoRoot `
      -LogPath (Join-Path $script:LogDir "pip-install.log") `
      -FailureMessage "Backend dependency install failed."
    $currentHash | Set-Content -LiteralPath $marker -Encoding ASCII
  } else {
    Write-LSStatus "Backend dependencies are current."
  }
}

function Ensure-NpmDeps {
  $packageFiles = @(
    (Join-Path $repoRoot "package.json"),
    (Join-Path $repoRoot "package-lock.json"),
    (Join-Path $repoRoot "apps\desktop\package.json")
  )
  $marker = Join-Path (Get-LSLauncherDir $repoRoot) "npm-dependencies.sha256"
  $currentHash = Get-LSFileHashText $packageFiles
  $installedHash = ""
  if (Test-Path -LiteralPath $marker) { $installedHash = (Get-Content -Raw -LiteralPath $marker).Trim() }
  $nodeModules = Join-Path $repoRoot "node_modules"

  if (($NoInstall -or $SkipNpmInstall) -and ((-not (Test-Path -LiteralPath $nodeModules)) -or $currentHash -ne $installedHash)) {
    Write-LSWarn "Skipping desktop dependency install even though node_modules is missing or package files changed."
    return
  }

  if ((-not (Test-Path -LiteralPath $nodeModules)) -or $currentHash -ne $installedHash) {
    Write-LSStatus "Installing desktop dependencies..."
    Invoke-LSLoggedCommand -FilePath $script:NpmCommand `
      -ArgumentList @("install") `
      -WorkingDirectory $repoRoot `
      -LogPath (Join-Path $script:LogDir "npm-install.log") `
      -FailureMessage "Desktop dependency install failed."
    $currentHash | Set-Content -LiteralPath $marker -Encoding ASCII
  } else {
    Write-LSStatus "Desktop dependencies are current."
  }
}

function Start-Backend {
  Resolve-LauncherPortConflict -Port $BackendPort -ServiceName "backend"
  if ($DockerBackend) {
    Write-LSStatus "Starting Docker backend on http://127.0.0.1:$BackendPort..."
    Invoke-LSLoggedCommand -FilePath $script:DockerCommand `
      -ArgumentList @("compose", "--profile", "mock", "up", "-d", "--build", "backend") `
      -WorkingDirectory $repoRoot `
      -LogPath (Join-Path $script:LogDir "docker-backend.log") `
      -FailureMessage "Docker backend failed to start."
    $state.DockerBackend = $true
    Write-LSState -RepoRoot $repoRoot -State $state
  } else {
    Write-LSStatus "Starting backend on http://127.0.0.1:$BackendPort..."
    $env:LOCAL_SCRIBE_HOST = "127.0.0.1"
    $env:LOCAL_SCRIBE_PORT = [string]$BackendPort
    if ($Mock -or -not $env:LOCAL_SCRIBE_PROVIDER) {
      $env:LOCAL_SCRIBE_PROVIDER = "mock"
    }
    $backend = Start-LSLoggedProcess -FilePath $script:VenvPython `
      -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", [string]$BackendPort) `
      -WorkingDirectory $repoRoot `
      -StdoutLog (Join-Path $script:LogDir "backend.out.log") `
      -StderrLog (Join-Path $script:LogDir "backend.err.log")
    $state.BackendPid = $backend.Id
    Write-LSState -RepoRoot $repoRoot -State $state
  }

  Write-LSStatus "Waiting for backend health..."
  if (-not (Wait-LSBackendHealth -BackendPort $BackendPort -TimeoutSeconds 60)) {
    Fail-Launcher "Backend did not become healthy. Check logs in $script:LogDir."
  }
}

function Start-Vite {
  Resolve-LauncherPortConflict -Port $VitePort -ServiceName "vite"
  Write-LSStatus "Starting Vite dev server on http://127.0.0.1:$VitePort..."
  $viteOutLog = Join-Path $script:LogDir "vite.out.log"
  $viteErrLog = Join-Path $script:LogDir "vite.err.log"
  $vite = Start-LSLoggedProcess -FilePath $script:NpmCommand `
    -ArgumentList @("--workspace", "@localscribe/desktop", "run", "dev", "--", "--host", "127.0.0.1", "--port", [string]$VitePort) `
    -WorkingDirectory $repoRoot `
    -StdoutLog $viteOutLog `
    -StderrLog $viteErrLog
  $state.VitePid = $vite.Id
  Write-LSState -RepoRoot $repoRoot -State $state

  Write-LSStatus "Waiting for Vite..."
  $deadline = (Get-Date).AddSeconds(60)
  while ((Get-Date) -lt $deadline) {
    if ($vite.HasExited) {
      $tail = Get-LSLogTail -Path $viteErrLog -Lines 30
      if (-not [string]::IsNullOrWhiteSpace($tail)) {
        Write-LSErrorMessage "Vite exited early. Recent Vite error log:"
        Write-Host $tail
      }
      Fail-Launcher "Vite exited before becoming reachable. Check logs in $script:LogDir."
    }
    if (Wait-LSVite -VitePort $VitePort -TimeoutSeconds 2) {
      return
    }
  }
  if (-not $vite.HasExited) {
    Fail-Launcher "Vite did not become reachable. Check logs in $script:LogDir."
  }
}

function Start-ElectronAndWait {
  if ($NoLaunch) {
    Write-LSStatus "Electron launch command verified: npm --workspace @localscribe/desktop run electron:dev"
    Write-LSStatus "-NoLaunch set. Skipping desktop launch after backend/Vite health checks."
    return 0
  }
  Write-LSStatus "Launching Local Scribe desktop app..."
  $env:VITE_DEV_SERVER_URL = "http://127.0.0.1:$VitePort"
  $env:LOCAL_SCRIBE_API_BASE = "http://127.0.0.1:$BackendPort/api"
  $electron = Start-LSLoggedProcess -FilePath $script:NpmCommand `
    -ArgumentList @("--workspace", "@localscribe/desktop", "run", "electron:dev") `
    -WorkingDirectory $repoRoot `
    -StdoutLog (Join-Path $script:LogDir "electron.out.log") `
    -StderrLog (Join-Path $script:LogDir "electron.err.log")
  $state.ElectronPid = $electron.Id
  Write-LSState -RepoRoot $repoRoot -State $state
  $electron.WaitForExit()
  return $electron.ExitCode
}

function Stop-StartedServices {
  Write-LSStatus "App exited. Shutting down services..."
  if ($state.ElectronPid) { Stop-LSProcessTree -ProcessId ([int]$state.ElectronPid) -Name "Electron" }
  if ($state.VitePid) { Stop-LSProcessTree -ProcessId ([int]$state.VitePid) -Name "Vite" }
  if ($state.BackendPid) { Stop-LSProcessTree -ProcessId ([int]$state.BackendPid) -Name "backend" }
  if ($state.DockerBackend -eq $true -and $script:DockerCommand) {
    try {
      & $script:DockerCommand compose --profile mock stop backend | Out-Null
    } catch {
      Write-LSWarn "Docker backend stop failed. Run scripts\stop-localscribe.ps1 if needed."
    }
  }
  if ($script:LauncherTemp) {
    Clear-LSDirectoryContents -Path $script:LauncherTemp | Out-Null
  }
  Remove-LSState -RepoRoot $repoRoot
}

try {
  Set-Location $repoRoot
  $logsRoot = Join-Path $repoRoot "app-data\logs\launcher"
  Ensure-LSDirectory $logsRoot
  $script:LogDir = Join-Path $logsRoot (Get-Date -Format "yyyyMMdd-HHmmss")
  Ensure-LSDirectory $script:LogDir
  $script:LauncherTemp = Join-Path $repoRoot "app-data\tmp\launcher"
  Ensure-LSDirectory $script:LauncherTemp

  Write-LSStatus "Launcher root: $repoRoot"
  Write-LSStatus "Logs: $script:LogDir"

  Invoke-LauncherInteractiveMenu
  Ensure-SystemDeps
  Initialize-LauncherModelProvider
  Invoke-LauncherGpuGate
  Ensure-PythonEnv
  Ensure-LivePocRuntime
  Invoke-LauncherOcrGate
  Invoke-LauncherModelGate
  Resolve-LauncherPortConflict -Port $BackendPort -ServiceName "backend"
  Resolve-LauncherPortConflict -Port $VitePort -ServiceName "vite"
  Ensure-NpmDeps
  Start-Backend
  Start-Vite
  $exitCode = Start-ElectronAndWait
} catch {
  $exitCode = 1
  if ($debugMode) {
    Write-Error $_
  } else {
    Write-LSErrorMessage ([string]$_.Exception.Message)
    if ($script:LogDir) {
      Write-Host "$script:LocalScribePrefix See logs: $script:LogDir"
    }
  }
} finally {
  Stop-StartedServices
}

exit $exitCode
