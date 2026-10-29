param([int]$Port = 4173)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$pidFile = Join-Path $root '.dashboard.pid'
$launchFile = Join-Path $root '.dashboard.launch.json'

function Get-LaunchConfig {
  $aoPath = [string]$env:AO_CLI_PATH
  if ($aoPath) {
    if (-not [IO.Path]::IsPathFullyQualified($aoPath) -or -not (Test-Path -LiteralPath $aoPath -PathType Leaf)) {
      throw "AO_CLI_PATH must be an absolute path to an existing ao binary."
    }
  }
  [ordered]@{
    ao_cli_path = if ($aoPath) { $aoPath } else { $null }
    hive_core_url = if ($env:HIVE_CORE_URL) { [string]$env:HIVE_CORE_URL } else { $null }
    hive_api_token_configured = [bool]$env:HIVE_API_TOKEN
  }
}

$launchConfig = Get-LaunchConfig
$launchJson = $launchConfig | ConvertTo-Json -Compress
if (Test-Path -LiteralPath $pidFile) {
  $oldPid = Get-Content -LiteralPath $pidFile -Raw
  $old = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
  if ($old -and $old.ProcessName -match 'python') {
    if (Test-Path -LiteralPath $launchFile) {
      $previous = Get-Content -LiteralPath $launchFile -Raw | ConvertFrom-Json | ConvertTo-Json -Compress
      if ($previous -ne $launchJson) {
        throw "Dashboard already running with a different launch configuration; stop it and restart to apply AO/HIVE environment changes."
      }
    }
    Write-Output "Already running: PID $oldPid"; exit 0
  }
  Remove-Item -LiteralPath $pidFile -Force
  Remove-Item -LiteralPath $launchFile -Force -ErrorAction SilentlyContinue
}
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw "Port $Port is already in use; no process was stopped." }
$proc = Start-Process -FilePath 'python' -ArgumentList 'server.py','--port',$Port,'--bind','127.0.0.1' -WorkingDirectory $root -PassThru -WindowStyle Hidden
Set-Content -LiteralPath $pidFile -Value $proc.Id -NoNewline
Set-Content -LiteralPath $launchFile -Value $launchJson -NoNewline
Write-Output "HIVE dashboard started at http://127.0.0.1:$Port/ (PID $($proc.Id))"
