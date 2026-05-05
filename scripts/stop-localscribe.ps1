[CmdletBinding()]
param(
  [switch]$Quiet
)

. "$PSScriptRoot\launcher-lib.ps1"

$ErrorActionPreference = "Stop"
$repoRoot = Get-LSRepoRoot
Set-Location $repoRoot
$state = Read-LSState -RepoRoot $repoRoot

if (-not $state) {
  if (-not $Quiet) {
    Write-LSStatus "No Local Scribe launcher state found. Nothing to stop."
  }
  exit 0
}

if (-not $Quiet) {
  Write-LSStatus "Stopping services started by launcher state..."
}

if ($state.ElectronPid) {
  Stop-LSProcessTree -ProcessId ([int]$state.ElectronPid) -Name "Electron"
}

if ($state.VitePid) {
  Stop-LSProcessTree -ProcessId ([int]$state.VitePid) -Name "Vite"
}

if ($state.BackendPid) {
  Stop-LSProcessTree -ProcessId ([int]$state.BackendPid) -Name "backend"
}

if ($state.DockerBackend -eq $true) {
  $docker = Get-LSCommand @("docker.exe", "docker")
  if ($docker) {
    Write-LSStatus "Stopping Docker backend container..."
    try {
      & $docker compose --profile mock stop backend | Out-Null
    } catch {
      Write-LSWarn "Docker backend stop failed. Check Docker Desktop and run: docker compose --profile mock stop backend"
    }
  }
}

Remove-LSState -RepoRoot $repoRoot

if (-not $Quiet) {
  Write-LSStatus "Stop complete. Unrelated processes were not touched."
}

exit 0
