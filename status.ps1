$root = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$pidFile = Join-Path $root '.dashboard.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'STOPPED'; exit 0 }
$dashboardPid = [int](Get-Content -LiteralPath $pidFile -Raw)
$proc = Get-Process -Id $dashboardPid -ErrorAction SilentlyContinue
if ($proc -and $proc.ProcessName -match 'python') { Write-Output "RUNNING PID $dashboardPid" } else { Write-Output 'STALE PID FILE' }
