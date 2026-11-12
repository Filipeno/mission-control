# Turns the mc-pc helper on or off (run again to switch). Same pattern as pc-waker's agent:
# a scheduled task starts it at login and re-checks every 5 minutes; conhost --headless hides the window.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$task = 'Mission Control PC helper'
$script = Join-Path $here 'mc-pc.ps1'

function Stop-Helper {
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like '*mc-pc.ps1*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $task -Confirm:$false
    Stop-Helper
    Write-Host 'mc-pc helper is now OFF.'
    exit
}
if (-not (Test-Path -LiteralPath (Join-Path $here 'mc-pc.json'))) {
    Write-Host 'mc-pc.json is missing. Copy mc-pc.json.example and fill it in.'
    exit 1
}
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\conhost.exe" `
    -Argument "--headless `"$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe`" -NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $here
$every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
try {
    Register-ScheduledTask -TaskName $task -Action $action -Trigger @($atLogon, $every5) -Settings $settings `
        -Description 'Mission Control: carries out Sleep from the phone app.' -ErrorAction Stop | Out-Null
} catch {
    Register-ScheduledTask -TaskName $task -Action $action -Trigger $every5 -Settings $settings `
        -Description 'Mission Control: carries out Sleep from the phone app.' | Out-Null
    Write-Host '(No logon trigger without admin rights: it starts within 5 minutes of login.)'
}
Stop-Helper
Start-ScheduledTask -TaskName $task
Write-Host 'mc-pc helper is now ON.'
