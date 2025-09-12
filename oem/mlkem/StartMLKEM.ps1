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

try {
    # ------------------- Main Work (BEGIN) -------------------

    # Install fonts
    C:\OEM\FontsToAdd\Add-Font.ps1 FontsToAdd\Fonts
    $env:chocolateyUseWindowsCompression = 'true'
    Set-ItemProperty -Path "HKLM:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell" -Name "ExecutionPolicy" -Value "Bypass" -Force
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

    choco feature enable -n allowGlobalConfirmation
    choco install python --version=3.11.9 --ignore-checksum --ignore-detected-reboot
    choco install chromium --version=139.0.7258.155 --ignore-checksums

    choco install firefox --version=142.0.1 --ignore-checksum --params '"/NoTaskbarShortcut /NoDesktopShortcut /NoStartMenuShortcut /NoAutoUpdate"'

    $repo = "\\host.lan\Data"
    Set-Location $repo
    py -3.11 -m venv C:\pqbench-venv
    C:\pqbench-venv\Scripts\python.exe -m pip install --upgrade pip
    C:\pqbench-venv\Scripts\python.exe -m pip install flask selenium webdriver-manager

    netsh advfirewall firewall add rule name="PQBench Flask" dir=in action=allow protocol=TCP localport=5000

    $env:MODE = "MLKEM"
    [Environment]::SetEnvironmentVariable('MODE','MLKEM','Machine')  # for the task at next boot

    $action  = New-ScheduledTaskAction -Execute "C:\pqbench-venv\Scripts\python.exe" -Argument "`"$repo\processorMLKEM.py`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName "PQBench-MLKEM" -Action $action -Trigger $trigger -User "Docker" -Password "admin" -RunLevel Highest -Force

    Start-Process -FilePath "C:\pqbench-venv\Scripts\python.exe" -ArgumentList "`"$repo\processorMLKEM.py`"" -WindowStyle Minimized
    # ------------------- Main Work (END) -------------------
}
finally {
    # ------------------- Sleep Prevention (STOP) -------------------
    if ($keepAwakeProc -and -not $keepAwakeProc.HasExited) {
        Stop-Process -Id $keepAwakeProc.Id -Force -ErrorAction SilentlyContinue
    }
}
