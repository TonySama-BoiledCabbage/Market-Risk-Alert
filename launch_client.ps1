$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BundledPython = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Port = 8765

if (Test-Path -LiteralPath $BundledPython) {
  $PythonPath = $BundledPython
} else {
  $PythonPath = "python"
}

$ServerScript = Join-Path $ProjectDir "web_client.py"
$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$OutLog = Join-Path $LogDir "web-client.out.log"
$ErrLog = Join-Path $LogDir "web-client.err.log"

function Test-ClientServer {
  try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/settings" -UseBasicParsing -TimeoutSec 2
    return $response.StatusCode -eq 200
  } catch {
    return $false
  }
}

if (-not (Test-ClientServer)) {
  Start-Process `
    -WindowStyle Hidden `
    -FilePath $PythonPath `
    -ArgumentList @("`"$ServerScript`"", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $ProjectDir `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog

  $ready = $false
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 250
    if (Test-ClientServer) {
      $ready = $true
      break
    }
  }

  if (-not $ready) {
    Write-Host "Market Risk Client failed to start."
    Write-Host "Error log: $ErrLog"
    if (Test-Path -LiteralPath $ErrLog) {
      Get-Content -LiteralPath $ErrLog -Tail 20
    }
    exit 1
  }
}

Start-Process "http://127.0.0.1:$Port"
