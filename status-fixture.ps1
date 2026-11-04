$root = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$pidFile = Join-Path $root '.fixture-dashboard.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'STOPPED'; exit 0 }
$fixturePid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $fixturePid" -ErrorAction SilentlyContinue
if ($process -and $process.Name -match '^python(\.exe)?$' -and [string]$process.CommandLine -match 'fixture_server\.py') {
  Write-Output "RUNNING PID $fixturePid"
} else {
  Write-Output 'STALE PID FILE'
}
