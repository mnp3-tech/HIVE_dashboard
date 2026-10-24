param([int]$Port = 4173)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$pidFile = Join-Path $root '.dashboard.pid'
if (Test-Path -LiteralPath $pidFile) {
  $oldPid = Get-Content -LiteralPath $pidFile -Raw
  $old = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
  if ($old -and $old.ProcessName -match 'python') { Write-Output "Already running: PID $oldPid"; exit 0 }
  Remove-Item -LiteralPath $pidFile -Force
}
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw "Port $Port is already in use; no process was stopped." }
$proc = Start-Process -FilePath 'python' -ArgumentList 'server.py','--port',$Port,'--bind','127.0.0.1' -WorkingDirectory $root -PassThru -WindowStyle Hidden
Set-Content -LiteralPath $pidFile -Value $proc.Id -NoNewline
Write-Output "HIVE dashboard started at http://127.0.0.1:$Port/ (PID $($proc.Id))"
