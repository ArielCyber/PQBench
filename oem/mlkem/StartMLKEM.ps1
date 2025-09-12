# Make sure TLS/WinGet/Choco-ready
Set-ExecutionPolicy Bypass -Scope LocalMachine -Force

# ------------------- Sleep Prevention (START) -------------------
# Run the Scroll Lock toggle in a background job so the script isn't blocked.
$keepAwakeJob = Start-Job {
    $WShell = New-Object -ComObject "WScript.Shell"
    while ($true) {
        $WShell.SendKeys("{SCROLLLOCK}")
        Start-Sleep -Milliseconds 100
        $WShell.SendKeys("{SCROLLLOCK}")
        Start-Sleep -Seconds 240
    }
}
try {
# ------------------- Main Work (BEGIN) -------------------

    # Handle Chrome
    .\FontsToAdd\Add-Font.ps1 FontsToAdd\Fonts

    # Install Chocolatey (stable way to get Python/Chrome/Firefox)
    # If you already keep a local bootstrap, you can replace this with winget.
    $env:chocolateyUseWindowsCompression = 'true'
    Set-ItemProperty -Path "HKLM:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell" -Name "ExecutionPolicy" -Value "Bypass" -Force
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

    # Core software
    choco feature enable -n allowGlobalConfirmation
    choco install python --version=3.11.9 --ignore-checksum --ignore-detected-reboot
    choco install googlechrome --version=139.0.7258.155 --ignore-checksum --ignore-detected-reboot --params "'/NoDesktopShortcuts /DoNotLaunchChrome'"
    choco install chromedriver --version=139.0.7258.154 --ignore-checksum --ignore-detected-reboot
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

    $env:MODE = "MLKEM"

    & "c:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --headless --disable-gpu --no-sandbox --enable-logging --print-to-pdf="C:/export/pdftest.pdf" https://www.google.com

    # Start now (first boot) so the service is up without reboot
    Start-Process -FilePath "C:\pqbench-venv\Scripts\python.exe" -ArgumentList "`"$repo\processorMLKEM.py`"" -WindowStyle Minimized

# ------------------- Main Work (END) -------------------
}
finally {
    # ------------------- Sleep Prevention (STOP) -------------------
    if ($keepAwakeJob -and ($keepAwakeJob.State -in 'Running','NotStarted')) {
        Stop-Job $keepAwakeJob -Force | Out-Null
    }
    Remove-Job $keepAwakeJob -Force -ErrorAction SilentlyContinue | Out-Null
}
