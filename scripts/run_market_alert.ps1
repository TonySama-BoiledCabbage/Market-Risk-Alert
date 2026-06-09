param(
  [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$InputPath = "",
  [string]$PythonPath = "",
  [ValidateSet("alert", "evening", "morning")]
  [string]$ReportMode = "alert",
  [switch]$FetchAlphaVantage,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InputPath)) {
  $InputPath = Join-Path $ProjectDir "data\latest_signals.json"
}

if (-not (Test-Path -LiteralPath $InputPath)) {
  throw "Input snapshot not found: $InputPath"
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
  $BundledPython = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path -LiteralPath $BundledPython) {
    $PythonPath = $BundledPython
  } else {
    $PythonPath = "python"
  }
}

$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$StdoutLog = Join-Path $LogDir "market-alert-$Timestamp.out.log"
$StderrLog = Join-Path $LogDir "market-alert-$Timestamp.err.log"

$Args = @(
  (Join-Path $ProjectDir "market_alert.py"),
  "--input", $InputPath,
  "--report-mode", $ReportMode
)

if ($FetchAlphaVantage) {
  $Args += "--fetch-alpha-vantage"
}

if ($DryRun) {
  $Args += "--dry-run"
}

Push-Location $ProjectDir
try {
  & $PythonPath @Args 1> $StdoutLog 2> $StderrLog
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
