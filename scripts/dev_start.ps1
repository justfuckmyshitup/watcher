param(
  [int]$Port = 8765,
  [int]$VitePort = 5173
)

$launcher = Join-Path $PSScriptRoot "start-localscribe.ps1"
& $launcher -BackendPort $Port -VitePort $VitePort -Mock
exit $LASTEXITCODE
