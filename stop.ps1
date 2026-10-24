$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$pidFile = Join-Path $root '.dashboard.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'Dashboard is not running.'; exit 0 }
$dashboardPid = [int](Get-Content -LiteralPath $pidFile -Raw)
$proc = Get-Process -Id $dashboardPid -ErrorAction SilentlyContinue
if ($proc -and $proc.ProcessName -match 'python') { Stop-Process -Id $dashboardPid; Write-Output "Stopped dashboard PID $dashboardPid." } else { Write-Output 'Recorded process no longer exists.' }
Remove-Item -LiteralPath $pidFile -Force
