# ------------------- Sleep Prevention (START) -------------------
$keepAwakeProc = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
  '-NoProfile','-ExecutionPolicy','Bypass','-Command',
@'
$ErrorActionPreference = "SilentlyContinue"
$ws = New-Object -ComObject WScript.Shell
while ($true) {
  $ws.SendKeys("{SCROLLLOCK}")
  Start-Sleep -Milliseconds 100
  $ws.SendKeys("{SCROLLLOCK}")
  Start-Sleep -Seconds 240
}
'@
)

# Ensure we always stop the job, even if something fails later.
try {
# ------------------- Main Work (BEGIN) -------------------

    # Install fonts
    C:\OEM\FontsToAdd\Add-Font.ps1 FontsToAdd\Fonts

    # Install Chocolatey (stable way to get Python/Chrome/Firefox)
    # If you already keep a local bootstrap, you can replace this with winget.
    $env:chocolateyUseWindowsCompression = 'true'
    Set-ItemProperty -Path "HKLM:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell" -Name "ExecutionPolicy" -Value "Bypass" -Force
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

    # Core software
    choco feature enable -n allowGlobalConfirmation
    choco install python --version=3.11.9 --ignore-detected-reboot --ignore-checksum
    choco install firefox --version=130.0.1 --ignore-checksum --params '"/NoTaskbarShortcut /NoDesktopShortcut /NoStartMenuShortcut /NoAutoUpdate"'
    choco install chromium --version=128.0.6613.120 --ignore-checksums

    # Python deps (run from shared repo path)
    $repo = "\\host.lan\Data"
    cd $repo
    # create an isolated venv for safety
    py -3.11 -m venv C:\pqbench-venv
    C:\pqbench-venv\Scripts\python.exe -m pip install --upgrade pip
    C:\pqbench-venv\Scripts\python.exe -m pip install flask selenium webdriver-manager

    # Open firewall for Flask port
    netsh advfirewall firewall add rule name="PQBench Flask" dir=in action=allow protocol=TCP localport=5000

    # Create a Scheduled Task to run the KYBER processor at boot (as the default Docker user)
    $action  = New-ScheduledTaskAction -Execute "C:\pqbench-venv\Scripts\python.exe" -Argument "`"$repo\processor.py`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName "PQBench-Kyber" -Action $action -Trigger $trigger -User "Docker" -Password "admin" -RunLevel Highest -Force

    $env:MODE = "KYBER"

    # Start now (first boot) so the service is up without reboot
    Start-Process -FilePath "C:\pqbench-venv\Scripts\python.exe" -ArgumentList "`"$repo\processor.py`"" -WindowStyle Minimized

# ------------------- Main Work (END) -------------------
}
finally {
    # ------------------- Sleep Prevention (STOP) -------------------
    if ($keepAwakeProc -and -not $keepAwakeProc.HasExited) {
        Stop-Process -Id $keepAwakeProc.Id -Force -ErrorAction SilentlyContinue
    }
}
