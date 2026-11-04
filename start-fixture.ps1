param([int]$Port = 4174)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$pidFile = Join-Path $root '.fixture-dashboard.pid'
$launchFile = Join-Path $root '.fixture-dashboard.launch.json'

function Get-FixtureProcess([int]$ProcessId) {
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if (-not $process) { return $null }
  if ($process.Name -notmatch '^python(\.exe)?$') { return $null }
  if ([string]$process.CommandLine -notmatch 'fixture_server\.py') { return $null }
  return $process
}

if (Test-Path -LiteralPath $pidFile) {
  $oldPid = [int](Get-Content -LiteralPath $pidFile -Raw)
  if (Get-FixtureProcess $oldPid) {
    Write-Output "Fixture already running: PID $oldPid"
    exit 0
  }
  Remove-Item -LiteralPath $pidFile -Force
  Remove-Item -LiteralPath $launchFile -Force -ErrorAction SilentlyContinue
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw "Port $Port is already in use; no process was stopped." }
$proc = Start-Process -FilePath 'python' -ArgumentList 'fixture_server.py','--port',$Port,'--bind','127.0.0.1' -WorkingDirectory $root -PassThru -WindowStyle Hidden
Set-Content -LiteralPath $pidFile -Value $proc.Id -NoNewline
Set-Content -LiteralPath $launchFile -Value (@{port=$Port; bind='127.0.0.1'; mode='read-only-runtime-fixture'} | ConvertTo-Json -Compress) -NoNewline
Write-Output "HIVE dashboard runtime fixture started at http://127.0.0.1:$Port/ (PID $($proc.Id))"
