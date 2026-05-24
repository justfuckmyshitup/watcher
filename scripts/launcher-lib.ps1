$script:WatcherPrefix = "[Watcher]"

function Write-WatcherStatus {
  param([string]$Message)
  Write-Host "$script:WatcherPrefix $Message"
}

function Write-WatcherWarn {
  param([string]$Message)
  Write-Host "$script:WatcherPrefix WARNING: $Message" -ForegroundColor Yellow
}

function Write-WatcherErrorMessage {
  param([string]$Message)
  Write-Host "$script:WatcherPrefix ERROR: $Message" -ForegroundColor Red
}

function Get-WatcherLogTail {
  param(
    [string]$Path,
    [int]$Lines = 20
  )
  if (-not (Test-Path -LiteralPath $Path)) {
    return ""
  }
  return ((Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue) -join "`n")
}

function Get-WatcherRepoRoot {
  return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Ensure-WatcherDirectory {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
  }
}

function Clear-WatcherDirectoryContents {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return 0
  }
  $root = (Resolve-Path -LiteralPath $Path).Path
  $removed = 0
  Get-ChildItem -Force -LiteralPath $root -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Name -eq ".gitkeep") { return }
    if ($_.PSIsContainer) {
      $removed += (Get-ChildItem -Recurse -File -Force -LiteralPath $_.FullName -ErrorAction SilentlyContinue | Measure-Object).Count
      Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    } else {
      Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
      $removed += 1
    }
  }
  return $removed
}

function Get-WatcherLauncherDir {
  param([string]$RepoRoot)
  $path = Join-Path $RepoRoot "app-data\launcher"
  Ensure-WatcherDirectory $path
  return $path
}

function Get-WatcherStatePath {
  param([string]$RepoRoot)
  return (Join-Path (Get-WatcherLauncherDir $RepoRoot) "watcher-processes.json")
}

function Read-WatcherState {
  param([string]$RepoRoot)
  $path = Get-WatcherStatePath $RepoRoot
  if (-not (Test-Path -LiteralPath $path)) {
    return $null
  }
  try {
    return (Get-Content -Raw -LiteralPath $path | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Write-WatcherState {
  param(
    [string]$RepoRoot,
    [hashtable]$State
  )
  $path = Get-WatcherStatePath $RepoRoot
  ($State | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $path -Encoding UTF8
}

function Remove-WatcherState {
  param([string]$RepoRoot)
  $path = Get-WatcherStatePath $RepoRoot
  if (Test-Path -LiteralPath $path) {
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
  }
}

function Test-WatcherProcessRunning {
  param([Nullable[int]]$ProcessId)
  if (-not $ProcessId) {
    return $false
  }
  try {
    $process = Get-Process -Id $ProcessId -ErrorAction Stop
    return -not $process.HasExited
  } catch {
    return $false
  }
}

function Get-WatcherChildProcessIds {
  param([int]$ParentProcessId)
  $children = @()
  try {
    $direct = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentProcessId" -ErrorAction Stop
    foreach ($child in $direct) {
      $children += [int]$child.ProcessId
      $children += Get-WatcherChildProcessIds -ParentProcessId ([int]$child.ProcessId)
    }
  } catch {
    return @()
  }
  return $children
}

function Stop-WatcherProcessTree {
  param(
    [Nullable[int]]$ProcessId,
    [string]$Name = "process"
  )
  if (-not (Test-WatcherProcessRunning $ProcessId)) {
    return
  }
  $children = Get-WatcherChildProcessIds -ParentProcessId ([int]$ProcessId)
  foreach ($childId in ($children | Select-Object -Unique | Sort-Object -Descending)) {
    if (Test-WatcherProcessRunning $childId) {
      Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
    }
  }
  if (Test-WatcherProcessRunning $ProcessId) {
    Write-WatcherStatus "Stopping $Name (PID $ProcessId)..."
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
  }
}

function Get-WatcherCommand {
  param([string[]]$Names)
  foreach ($name in $Names) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
      return $command.Source
    }
  }
  return $null
}

function Test-WatcherPortOpen {
  param([int]$Port)
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    $connected = $async.AsyncWaitHandle.WaitOne(400)
    if ($connected) {
      $client.EndConnect($async)
      return $true
    }
    return $false
  } catch {
    return $false
  } finally {
    $client.Close()
  }
}

function Get-WatcherPortOwner {
  param([int]$Port)
  try {
    $connection = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    if ($connection) {
      return [int]$connection.OwningProcess
    }
  } catch {
    try {
      $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
      if ($connection) {
        return [int]$connection.OwningProcess
      }
    } catch {
      return $null
    }
  }
  return $null
}

function Get-WatcherProcessCommandLine {
  param([Nullable[int]]$ProcessId)
  if (-not $ProcessId) {
    return ""
  }
  try {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    return [string]$process.CommandLine
  } catch {
    return ""
  }
}

function Invoke-WatcherHealthCheck {
  param([int]$BackendPort)
  try {
    return Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 2 -ErrorAction Stop
  } catch {
    return $null
  }
}

function Wait-WatcherBackendHealth {
  param(
    [int]$BackendPort,
    [int]$TimeoutSeconds = 45
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $health = Invoke-WatcherHealthCheck -BackendPort $BackendPort
    if ($health -and $health.ok -eq $true -and $health.app -eq "Watcher") {
      return $true
    }
    Start-Sleep -Milliseconds 600
  }
  return $false
}

function Wait-WatcherVite {
  param(
    [int]$VitePort,
    [int]$TimeoutSeconds = 45
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -Uri "http://127.0.0.1:$VitePort" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        return $true
      }
    } catch {
      Start-Sleep -Milliseconds 600
    }
  }
  return $false
}

function Invoke-WatcherLoggedCommand {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [string]$LogPath,
    [string]$FailureMessage
  )
  Ensure-WatcherDirectory (Split-Path -Parent $LogPath)
  Push-Location $WorkingDirectory
  $oldPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $output = & $FilePath @ArgumentList 2>&1
    $exit = $LASTEXITCODE
    $output | Out-File -LiteralPath $LogPath -Encoding UTF8
  } finally {
    $ErrorActionPreference = $oldPreference
    Pop-Location
  }
  if ($exit -ne 0) {
    throw "$FailureMessage See log: $LogPath"
  }
}

function Start-WatcherLoggedProcess {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [string]$StdoutLog,
    [string]$StderrLog
  )
  Repair-WatcherProcessPathEnvironment
  Ensure-WatcherDirectory (Split-Path -Parent $StdoutLog)
  Ensure-WatcherDirectory (Split-Path -Parent $StderrLog)
  return Start-Process -FilePath $FilePath `
    -ArgumentList $ArgumentList `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -WindowStyle Hidden `
    -PassThru
}

function Get-WatcherFileHashText {
  param([string[]]$Paths)
  $parts = @()
  foreach ($path in $Paths) {
    if (Test-Path -LiteralPath $path) {
      $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $path
      $parts += "$($hash.Path):$($hash.Hash)"
    }
  }
  $bytes = [System.Text.Encoding]::UTF8.GetBytes(($parts -join "`n"))
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
  } finally {
    $sha.Dispose()
  }
}

function Confirm-WatcherAction {
  param(
    [string]$Prompt,
    [switch]$AssumeYes
  )
  if ($AssumeYes) {
    return $true
  }
  $answer = Read-Host "$script:WatcherPrefix $Prompt [y/N]"
  return $answer -match "^(y|yes)$"
}

function Repair-WatcherProcessPathEnvironment {
  $pathValue = [System.Environment]::GetEnvironmentVariable("Path", "Process")
  if ([string]::IsNullOrWhiteSpace($pathValue)) {
    $pathValue = [System.Environment]::GetEnvironmentVariable("PATH", "Process")
  }
  if ([string]::IsNullOrWhiteSpace($pathValue)) {
    return
  }
  [System.Environment]::SetEnvironmentVariable("PATH", $null, "Process")
  [System.Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
}
