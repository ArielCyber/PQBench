# ------------------- Sleep Prevention (START) -------------------
$keepAwakeProc = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
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
try
{
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

    # --- Python venv + robust pip bootstrap ---
    $repo = "\\host.lan\Data"
    cd $repo

    # Always recreate a clean venv with up-to-date seed packages
    py -3.11 -m venv --clear --upgrade-deps C:\pqbench-venv

    $py = "C:\pqbench-venv\Scripts\python.exe"

    function Test-PipNullBytes
    {
        $pipDir = Join-Path (Split-Path $py) "..\Lib\site-packages\pip" | Resolve-Path
        Get-ChildItem $pipDir -Recurse -Include *.py | ForEach-Object {
            $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
            if ($bytes -contains 0)
            {
                return $true
            }
        }
        return $false
    }

    function Invoke-WithRetry([scriptblock]$Block, [int]$Retries = 3)
    {
        for ($i = 1; $i -le $Retries; $i++) {
            try
            {
                & $Block; return
            }
            catch
            {
                if ($i -eq $Retries)
                {
                    throw
                }
                Start-Sleep -Seconds ([int][Math]::Min(5*$i, 15))
            }
        }
    }

    # Seed/repair pip from the stdlib wheels first
    & $py -m ensurepip --upgrade

    # If null bytes slipped in (or anything looks broken), nuke pip and reseed
    if (Test-PipNullBytes)
    {
        Write-Host "Detected corrupted pip; repairing..."
        Remove-Item (Join-Path (Split-Path $py) "..\Lib\site-packages\pip*") -Recurse -Force -ErrorAction SilentlyContinue
        & $py -m ensurepip --upgrade
    }

    # Now force-reinstall a clean pip from PyPI, no cache (with retries)
    $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
    Invoke-WithRetry { & $py -m pip install --no-cache-dir --upgrade --force-reinstall pip }
    # Optionally also refresh build tools
    Invoke-WithRetry { & $py -m pip install --no-cache-dir --upgrade setuptools wheel }

    # Finally your deps
    Invoke-WithRetry { & $py -m pip install --no-cache-dir flask selenium webdriver-manager }

    # Open firewall for Flask port
    netsh advfirewall firewall add rule name="PQBench Flask" dir=in action=allow protocol=TCP localport=5000

    # Create a Scheduled Task to run the KYBER processor at boot (as the default Docker user)
    $action = New-ScheduledTaskAction -Execute "C:\pqbench-venv\Scripts\python.exe" -Argument "`"$repo\processor.py`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName "PQBench-Kyber" -Action $action -Trigger $trigger -User "Docker" -Password "admin" -RunLevel Highest -Force

    # Set env variables
    $env:MODE = "KYBER"
    [Environment]::SetEnvironmentVariable('MODE', 'KYBER', 'Machine')  # for the task at next boot
    $env:SNIFFER_URL = "http://172.18.0.1:8080"
    [Environment]::SetEnvironmentVariable('SNIFFER_URL', 'http://172.18.0.1:8080', 'Machine')  # for the task at next boot

    # Start now (first boot) so the service is up without reboot
    Start-Process -FilePath "C:\pqbench-venv\Scripts\python.exe" -ArgumentList "`"$repo\processor.py`"" -WindowStyle Minimized

    # ------------------- Main Work (END) -------------------
}
finally
{
    # ------------------- Sleep Prevention (STOP) -------------------
    if ($keepAwakeProc -and -not $keepAwakeProc.HasExited)
    {
        Stop-Process -Id $keepAwakeProc.Id -Force -ErrorAction SilentlyContinue
    }
}
