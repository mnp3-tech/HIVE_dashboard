$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$pidFile = Join-Path $root '.fixture-dashboard.pid'
$launchFile = Join-Path $root '.fixture-dashboard.launch.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'Runtime fixture is not running.'; exit 0 }
$fixturePid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $fixturePid" -ErrorAction SilentlyContinue
if ($process -and $process.Name -match '^python(\.exe)?$' -and [string]$process.CommandLine -match 'fixture_server\.py') {
  Stop-Process -Id $fixturePid
  Write-Output "Stopped runtime fixture PID $fixturePid."
} else {
  Write-Output 'Recorded fixture process no longer exists or PID was not a fixture process.'
}
Remove-Item -LiteralPath $pidFile -Force
Remove-Item -LiteralPath $launchFile -Force -ErrorAction SilentlyContinue
