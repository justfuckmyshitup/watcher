[CmdletBinding()]
param(
  [switch]$RequireGpu,
  [switch]$RequireCudaProvider,
  [switch]$RequirePaddleGpu,
  [switch]$SkipPackageProbe,
  [switch]$Json,
  [string]$PythonPath
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-LSRepoRoot
Set-Location $repoRoot

function ConvertTo-LSInt {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) {
    return $null
  }
  $match = [regex]::Match($Value.Replace(",", ""), "\d+")
  if (-not $match.Success) {
    return $null
  }
  return [int]$match.Value
}

function Invoke-LSNvidiaQuery {
  param([string[]]$Fields)
  $nvidia = Get-LSCommand @("nvidia-smi.exe", "nvidia-smi")
  if (-not $nvidia) {
    return $null
  }
  $query = ($Fields -join ",")
  $output = & $nvidia "--query-gpu=$query" "--format=csv,noheader,nounits" 2>$null
  if ($LASTEXITCODE -ne 0) {
    return $null
  }
  return @($output)
}

function Get-LSNvidiaGpus {
  $fields = @("name", "memory.total", "memory.free", "driver_version", "compute_cap")
  $rows = Invoke-LSNvidiaQuery -Fields $fields
  if (-not $rows) {
    $fields = @("name", "memory.total", "memory.free", "driver_version")
    $rows = Invoke-LSNvidiaQuery -Fields $fields
  }
  if (-not $rows) {
    return @()
  }
  $gpus = @()
  foreach ($row in $rows) {
    if ([string]::IsNullOrWhiteSpace($row)) { continue }
    $parts = @($row -split "," | ForEach-Object { $_.Trim() })
    $gpu = [ordered]@{}
    for ($i = 0; $i -lt $fields.Count; $i++) {
      $field = $fields[$i]
      $value = if ($i -lt $parts.Count) { $parts[$i] } else { "" }
      switch ($field) {
        "name" { $gpu.name = $value }
        "memory.total" { $gpu.memory_total_mb = ConvertTo-LSInt $value }
        "memory.free" { $gpu.memory_free_mb = ConvertTo-LSInt $value }
        "driver_version" { $gpu.driver_version = $value }
        "compute_cap" { $gpu.compute_capability = if ($value) { $value } else { $null } }
      }
    }
    $gpus += [pscustomobject]$gpu
  }
  return $gpus
}

function Resolve-LSPython {
  if ($PythonPath) {
    return $PythonPath
  }
  $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) {
    return $venvPython
  }
  return Get-LSCommand @("python.exe", "python")
}

function Get-LSPythonGpuPackages {
  if ($SkipPackageProbe) {
    return [ordered]@{
      probe_skipped = $true
      onnxruntime_cuda_provider_available = $false
      paddle_gpu_available = $false
    }
  }

  $python = Resolve-LSPython
  if (-not $python) {
    return [ordered]@{
      probe_error = "Python was not found."
      onnxruntime_cuda_provider_available = $false
      paddle_gpu_available = $false
    }
  }

  $code = @'
import importlib.util
import json

def exists(name):
    return importlib.util.find_spec(name) is not None

data = {
    "python": True,
    "onnxruntime_installed": exists("onnxruntime"),
    "onnxruntime_genai_installed": exists("onnxruntime_genai"),
    "onnxruntime_providers": [],
    "onnxruntime_cuda_provider_available": False,
    "paddle_installed": exists("paddle"),
    "paddle_cuda_compiled": False,
    "paddle_cuda_device_count": 0,
    "paddle_gpu_available": False,
}

if data["onnxruntime_installed"]:
    try:
        import onnxruntime as ort
        providers = list(ort.get_available_providers())
        data["onnxruntime_providers"] = providers
        data["onnxruntime_cuda_provider_available"] = "CUDAExecutionProvider" in providers
    except Exception as exc:
        data["onnxruntime_error"] = str(exc)

if data["paddle_installed"]:
    try:
        import paddle
        cuda_compiled = bool(paddle.device.is_compiled_with_cuda())
        device_count = int(paddle.device.cuda.device_count()) if cuda_compiled else 0
        data["paddle_cuda_compiled"] = cuda_compiled
        data["paddle_cuda_device_count"] = device_count
        data["paddle_gpu_available"] = cuda_compiled and device_count > 0
    except Exception as exc:
        data["paddle_error"] = str(exc)

print(json.dumps(data))
'@

  $probeDir = Join-Path $repoRoot "app-data\tmp\gpu-probe"
  Ensure-LSDirectory $probeDir
  $probePath = Join-Path $probeDir "gpu-package-probe-$([guid]::NewGuid().ToString('N')).py"
  try {
    $code | Set-Content -LiteralPath $probePath -Encoding UTF8
    $oldPreference = $ErrorActionPreference
    try {
      $ErrorActionPreference = "Continue"
      $output = & $python $probePath 2>$null
    } finally {
      $ErrorActionPreference = $oldPreference
    }
    if ($LASTEXITCODE -ne 0 -or -not $output) {
      return [ordered]@{
        probe_error = "Python GPU package probe failed."
        onnxruntime_cuda_provider_available = $false
        paddle_gpu_available = $false
      }
    }
    $jsonLine = @($output | Where-Object { $_ -match "^\s*\{" } | Select-Object -Last 1)
    if (-not $jsonLine) {
      return [ordered]@{
        probe_error = "Python GPU package probe did not emit JSON."
        onnxruntime_cuda_provider_available = $false
        paddle_gpu_available = $false
      }
    }
    return ($jsonLine -join "`n" | ConvertFrom-Json)
  } catch {
    return [ordered]@{
      probe_error = $_.Exception.Message
      onnxruntime_cuda_provider_available = $false
      paddle_gpu_available = $false
    }
  } finally {
    if (Test-Path -LiteralPath $probePath) {
      Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
    }
    try {
      $remaining = Get-ChildItem -Force -LiteralPath $probeDir -ErrorAction SilentlyContinue
      if (-not $remaining) {
        Remove-Item -LiteralPath $probeDir -Force -ErrorAction SilentlyContinue
      }
    } catch {
      $null = $_
    }
  }
}

function Add-LSUnique {
  param(
    [System.Collections.ArrayList]$List,
    [string]$Value
  )
  if (-not $List.Contains($Value)) {
    [void]$List.Add($Value)
  }
}

$gpus = @(Get-LSNvidiaGpus)
$hardwareReady = $gpus.Count -gt 0
$packages = Get-LSPythonGpuPackages
$cudaReady = [bool]$packages.onnxruntime_cuda_provider_available
$paddleReady = [bool]$packages.paddle_gpu_available
$providerReady = $cudaReady -or $paddleReady
$warnings = [System.Collections.ArrayList]::new()
$errors = [System.Collections.ArrayList]::new()
$actions = [System.Collections.ArrayList]::new()

if (-not $hardwareReady) {
  $message = "No NVIDIA GPU was detected with nvidia-smi."
  if ($RequireGpu) {
    [void]$errors.Add($message)
  } else {
    [void]$warnings.Add($message)
  }
  Add-LSUnique -List $actions -Value "Install or update the NVIDIA driver, then rerun .\scripts\check-gpu.ps1."
}

if ($RequireCudaProvider -and -not $cudaReady) {
  [void]$errors.Add("ONNX Runtime CUDA execution provider is not available.")
  Add-LSUnique -List $actions -Value "Install a CUDA-capable ONNX Runtime GenAI profile after confirming CUDA/cuDNN compatibility."
}

if ($RequirePaddleGpu -and -not $paddleReady) {
  [void]$errors.Add("PaddlePaddle GPU support is not available.")
  Add-LSUnique -List $actions -Value "Install the PaddlePaddle GPU package that matches the local NVIDIA driver/CUDA profile."
}

if ($hardwareReady -and -not $providerReady -and -not $SkipPackageProbe) {
  [void]$warnings.Add("NVIDIA GPU detected, but no Python OCR/LLM GPU provider is ready yet.")
}

$gpuProvider = "none"
if ($cudaReady) {
  $gpuProvider = "onnxruntime-cuda"
} elseif ($paddleReady) {
  $gpuProvider = "paddle-gpu"
} elseif ($hardwareReady) {
  $gpuProvider = "nvidia-detected"
}
$primaryGpu = $null
if ($gpus.Count -gt 0) {
  $primaryGpu = $gpus[0]
}

$report = [ordered]@{
  gpu_required = [bool]$RequireGpu
  cuda_provider_required = [bool]$RequireCudaProvider
  paddle_gpu_required = [bool]$RequirePaddleGpu
  gpu_ready = ($hardwareReady -and $errors.Count -eq 0)
  hardware_ready = $hardwareReady
  provider_ready = $providerReady
  gpu_provider = $gpuProvider
  nvidia_smi_available = [bool](Get-LSCommand @("nvidia-smi.exe", "nvidia-smi"))
  gpus = $gpus
  primary_gpu = $primaryGpu
  packages = $packages
  warnings = @($warnings)
  errors = @($errors)
  recommended_actions = @($actions)
  checked_at = (Get-Date).ToString("o")
}

if ($Json) {
  $report | ConvertTo-Json -Depth 8
} else {
  Write-LSStatus "Checking NVIDIA GPU..."
  if ($hardwareReady) {
    $primary = $gpus[0]
    Write-LSStatus "GPU found: $($primary.name), driver $($primary.driver_version), VRAM $($primary.memory_free_mb)/$($primary.memory_total_mb) MB free."
  } else {
    Write-LSWarn "No NVIDIA GPU found via nvidia-smi."
  }
  if (-not $SkipPackageProbe) {
    Write-LSStatus "ONNX Runtime CUDA provider: $(if ($cudaReady) { 'ready' } else { 'not ready' })"
    Write-LSStatus "PaddlePaddle GPU: $(if ($paddleReady) { 'ready' } else { 'not ready' })"
  }
  foreach ($warning in $warnings) {
    Write-LSWarn $warning
  }
  foreach ($errorItem in $errors) {
    Write-LSErrorMessage $errorItem
  }
  if ($actions.Count -gt 0) {
    Write-LSStatus "Recommended action:"
    foreach ($action in $actions) {
      Write-Host "  - $action"
    }
  }
}

if ($errors.Count -gt 0) {
  exit 1
}
exit 0
