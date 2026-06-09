param(
  [string]$EveningTaskName = "Market Risk Daily 22 Report",
  [string]$MorningTaskName = "Market Risk Market Open Advice"
)

$ErrorActionPreference = "Stop"

foreach ($TaskName in @($EveningTaskName, $MorningTaskName)) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task: $TaskName"
  } else {
    Write-Host "Scheduled task not found: $TaskName"
  }
}
