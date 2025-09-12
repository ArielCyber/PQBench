# Prevent system from sleeping (requires admin privileges)
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class SleepUtil {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@

# Flags:
# ES_CONTINUOUS = 0x80000000
# ES_SYSTEM_REQUIRED = 0x00000001
# ES_DISPLAY_REQUIRED = 0x00000002
[void][SleepUtil]::SetThreadExecutionState(0x80000001 -bor 0x80000002)

# Make sure TLS/WinGet/Choco-ready
Set-ExecutionPolicy Bypass -Scope LocalMachine -Force

# Install Chocolatey (stable way to get Python/Chrome/Firefox)
# If you already keep a local bootstrap, you can replace this with winget.
$env:chocolateyUseWindowsCompression = 'true'
Set-ItemProperty -Path "HKLM:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell" -Name "ExecutionPolicy" -Value "Bypass" -Force
Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Core software
choco feature enable -n allowGlobalConfirmation
choco install python --version=3.11.9 --ignore-checksum --ignore-detected-reboot
choco install googlechrome --version=139.0.7258.155 --ignore-checksum  --ignore-detected-reboot --params "'/NoDesktopShortcuts /DoNotLaunchChrome /NoAutoUpdate'"
choco install firefox --version=142.0.1 --ignore-checksum --params '"/NoTaskbarShortcut /NoDesktopShortcut /NoStartMenuShortcut /NoAutoUpdate"'

# Python deps (run from shared repo path)
$repo = "\\host.lan\Data"
cd $repo
# create an isolated venv for safety
py -3.11 -m venv C:\pqbench-venv
C:\pqbench-venv\Scripts\python.exe -m pip install --upgrade pip
C:\pqbench-venv\Scripts\python.exe -m pip install flask selenium webdriver-manager

# Open firewall for Flask port
netsh advfirewall firewall add rule name="PQBench Flask" dir=in action=allow protocol=TCP localport=5000

# Create a Scheduled Task to run the MLKEM processor at boot (as the default Docker user)
$action  = New-ScheduledTaskAction -Execute "C:\pqbench-venv\Scripts\python.exe" -Argument "`"$repo\processorMLKEM.py`""
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "PQBench-MLKEM" -Action $action -Trigger $trigger -User "Docker" -Password "admin" -RunLevel Highest -Force

# Start now (first boot) so the service is up without reboot
Start-Process -FilePath "C:\pqbench-venv\Scripts\python.exe" -ArgumentList "`"$repo\processorMLKEM.py`"" -WindowStyle Minimized


# Allow sleep again
[void][SleepUtil]::SetThreadExecutionState(0x80000000)