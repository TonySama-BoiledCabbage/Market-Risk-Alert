param(
  [string]$TaskName = "Market Risk Telegram Alert",
  [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$InputPath = "",
  [int]$IntervalMinutes = 15,
  [string]$StartTime = "09:20",
  [int]$DurationHours = 8,
  [switch]$FetchAlphaVantage
)

$ErrorActionPreference = "Stop"

if ($IntervalMinutes -lt 5) {
  throw "IntervalMinutes should be at least 5 to avoid noisy alerts and API pressure."
}

if ([string]::IsNullOrWhiteSpace($InputPath)) {
  $InputPath = Join-Path $ProjectDir "data\latest_signals.json"
}

$RunnerPath = Join-Path $ProjectDir "scripts\run_market_alert.ps1"
if (-not (Test-Path -LiteralPath $RunnerPath)) {
  throw "Runner script not found: $RunnerPath"
}

$ActionArgs = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$RunnerPath`"",
  "-ProjectDir", "`"$ProjectDir`"",
  "-InputPath", "`"$InputPath`""
)

if ($FetchAlphaVantage) {
  $ActionArgs += "-FetchAlphaVantage"
}

$At = [datetime]::ParseExact($StartTime, "HH:mm", $null)
$StartBoundary = (Get-Date -Hour $At.Hour -Minute $At.Minute -Second 0).ToString("yyyy-MM-ddTHH:mm:ss")
$IntervalIso = "PT${IntervalMinutes}M"
$DurationIso = "PT${DurationHours}H"
$ActionArgument = ($ActionArgs -join " ")
$UserId = "$env:USERDOMAIN\$env:USERNAME"

function Escape-Xml {
  param([string]$Value)
  return [System.Security.SecurityElement]::Escape($Value)
}

$TaskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Checks professional market risk signals, then sends Telegram alerts when thresholds are triggered.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$(Escape-Xml $StartBoundary)</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>
          <Monday />
          <Tuesday />
          <Wednesday />
          <Thursday />
          <Friday />
        </DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
      <Repetition>
        <Interval>$(Escape-Xml $IntervalIso)</Interval>
        <Duration>$(Escape-Xml $DurationIso)</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$(Escape-Xml $UserId)</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>$(Escape-Xml $ActionArgument)</Arguments>
      <WorkingDirectory>$(Escape-Xml $ProjectDir)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $TaskName -Xml $TaskXml -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Cadence: weekdays every $IntervalMinutes minutes from $StartTime for $DurationHours hours"
Write-Host "Input snapshot: $InputPath"
Write-Host "Project dir: $ProjectDir"
