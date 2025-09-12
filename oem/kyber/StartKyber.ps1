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
# Ensure we always stop the job, even if something fails later.
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
    choco install python --version=3.11.9 --ignore-detected-reboot --ignore-checksum
    choco install firefox --version=130.0.1 --ignore-checksum --params '"/NoTaskbarShortcut /NoDesktopShortcut /NoStartMenuShortcut /NoAutoUpdate"'

    # Chrome download
    $chromeUrl = "https://storage.googleapis.com/chrome-for-testing-public/128.0.6613.137/win64/chrome-win64.zip"
    $tempZip   = "C:\temp\chrome.zip"
    $destPath  = "C:\Program Files"

    # Create temp folder if it doesn't exist
    if (-not (Test-Path "C:\temp")) {
        New-Item -ItemType Directory -Path "C:\temp" | Out-Null
    }

    # Download Chrome zip
    Invoke-WebRequest -Uri $chromeUrl -OutFile $tempZip

    # Extract to destination
    Expand-Archive -Path $tempZip -DestinationPath $destPath -Force

    # Remove zip
    Remove-Item $tempZip -Force

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
    $action  = New-ScheduledTaskAction -Execute "C:\pqbench-venv\Scripts\python.exe" -Argument "`"$repo\processorKyber.py`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName "PQBench-Kyber" -Action $action -Trigger $trigger -User "Docker" -Password "admin" -RunLevel Highest -Force

    $env:MODE = "KYBER"

    & "c:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --headless --disable-gpu --no-sandbox --enable-logging --print-to-pdf="C:/export/pdftest.pdf" https://www.google.com

    # Start now (first boot) so the service is up without reboot
    Start-Process -FilePath "C:\pqbench-venv\Scripts\python.exe" -ArgumentList "`"$repo\processorKyber.py`"" -WindowStyle Minimized

# ------------------- Main Work (END) -------------------
}
finally {
    # ------------------- Sleep Prevention (STOP) -------------------
    if ($keepAwakeJob -and ($keepAwakeJob.State -in 'Running','NotStarted')) {
        Stop-Job $keepAwakeJob -Force | Out-Null
    }
    Remove-Job $keepAwakeJob -Force -ErrorAction SilentlyContinue | Out-Null
}
