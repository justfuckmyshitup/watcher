[CmdletBinding()]
param(
  [switch]$Quiet
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-WatcherRepoRoot
Set-Location $repoRoot
$state = Read-WatcherState -RepoRoot $repoRoot

if (-not $state) {
  if (-not $Quiet) {
    Write-WatcherStatus "No Watcher launcher state found. Nothing to stop."
  }
  exit 0
}

if (-not $Quiet) {
  Write-WatcherStatus "Stopping services started by launcher state..."
}

if ($state.ElectronPid) {
  Stop-WatcherProcessTree -ProcessId ([int]$state.ElectronPid) -Name "Electron"
}

if ($state.VitePid) {
  Stop-WatcherProcessTree -ProcessId ([int]$state.VitePid) -Name "Vite"
}

if ($state.BackendPid) {
  Stop-WatcherProcessTree -ProcessId ([int]$state.BackendPid) -Name "backend"
}

if ($state.DockerBackend -eq $true) {
  $docker = Get-WatcherCommand @("docker.exe", "docker")
  if ($docker) {
    Write-WatcherStatus "Stopping Docker backend container..."
    try {
      & $docker compose --profile mock stop backend | Out-Null
    } catch {
      Write-WatcherWarn "Docker backend stop failed. Check Docker Desktop and run: docker compose --profile mock stop backend"
    }
  }
}

Remove-WatcherState -RepoRoot $repoRoot

if (-not $Quiet) {
  Write-WatcherStatus "Stop complete. Unrelated processes were not touched."
}

exit 0
