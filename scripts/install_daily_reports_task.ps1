param(
  [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$InputPath = "",
  [string]$EveningTaskName = "Market Risk Daily 22 Report",
  [string]$MorningTaskName = "Market Risk Market Open Advice",
  [string]$EveningTime = "22:00",
  [string]$MorningTime = "09:45",
  [switch]$FetchAlphaVantage
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InputPath)) {
  $InputPath = Join-Path $ProjectDir "data\latest_signals.json"
}

$RunnerPath = Join-Path $ProjectDir "scripts\run_market_alert.ps1"
if (-not (Test-Path -LiteralPath $RunnerPath)) {
  throw "Runner script not found: $RunnerPath"
}

function New-ReportAction {
  param(
    [string]$Mode
  )

  $ActionArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$RunnerPath`"",
    "-ProjectDir", "`"$ProjectDir`"",
    "-InputPath", "`"$InputPath`"",
    "-ReportMode", $Mode
  )

  if ($FetchAlphaVantage) {
    $ActionArgs += "-FetchAlphaVantage"
  }

  New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($ActionArgs -join " ") `
    -WorkingDirectory $ProjectDir
}

$Settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$EveningTrigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($EveningTime, "HH:mm", $null))
$MorningTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At ([datetime]::ParseExact($MorningTime, "HH:mm", $null))

Register-ScheduledTask `
  -TaskName $EveningTaskName `
  -Action (New-ReportAction -Mode "evening") `
  -Trigger $EveningTrigger `
  -Settings $Settings `
  -Principal $Principal `
  -Description "Sends a 22:00 daily market recap by Telegram regardless of alert threshold." `
  -Force | Out-Null

Register-ScheduledTask `
  -TaskName $MorningTaskName `
  -Action (New-ReportAction -Mode "morning") `
  -Trigger $MorningTrigger `
  -Settings $Settings `
  -Principal $Principal `
  -Description "Sends 09:45 market-open advice by Telegram regardless of alert threshold." `
  -Force | Out-Null

Write-Host "Installed scheduled report tasks:"
Write-Host "- $EveningTaskName at $EveningTime daily"
Write-Host "- $MorningTaskName at $MorningTime weekdays"
Write-Host "Input snapshot: $InputPath"
