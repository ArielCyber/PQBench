<# 
  DumpcapForward.ps1
  Stream live PCAP from Windows host (Docker Desktop / vEthernet NAT) to a remote sniffer over SSH.

  Prereqs on 192.168.1.100 (this Windows host):
   - Wireshark installed (for dumpcap.exe). Confirm path below if custom.
   - OpenSSH Client installed (Settings > Apps > Optional features > Add "OpenSSH Client").
   - This script should run with enough privileges to capture (Admin / LocalSystem).

  Remote (192.168.1.224):
   - OpenSSH Server enabled (so we can `ssh user@192.168.1.224 "cat > /path.pcap"`)

  Usage:
   - Adjust the CONFIG section, then run (as Admin):
     powershell.exe -ExecutionPolicy Bypass -File C:\pqbench\DumpcapForward.ps1
#>

# ----------------------------- CONFIG ---------------------------------
$RemoteHost       = "192.168.1.224"              # sniffer box
$RemoteUser       = "Home_Server"                # Linux user on the sniffer
$RemotePath       = "C:\Users\Home_Server\Documents\Git\PQBench\output\windows_output\pqbench-stream.pcap"   # where to write the live stream on remote
$InterfaceMatch   = "vEthernet (nat)"            # adapter name to capture on
$CaptureFilter    = "tcp port 443"               # BPF (leave "" for all traffic)
$ReconnectDelay   = 5                            # seconds between reconnect attempts

# Paths (change if Wireshark or SSH is elsewhere)
$DumpcapPath      = "C:\Program Files\Wireshark\dumpcap.exe"
$SshPath          = "C:\Windows\System32\OpenSSH\ssh.exe"

# Logging
$LogDir           = "C:\Users\Home_Server\Documents\Git\PQBench\logs"
$LogFile          = Join-Path $LogDir "DumpcapForward.log"
# ----------------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($msg) {
  $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  "$ts $msg" | Tee-Object -FilePath $LogFile -Append
}

function Assert-File($path, $hint) {
  if (-not (Test-Path $path)) {
    throw "Missing $hint at: $path"
  }
}

# Validate tools exist
Assert-File $DumpcapPath "dumpcap.exe (install Wireshark)"
Assert-File $SshPath "ssh.exe (install OpenSSH Client)"

# Resolve the capture interface name using dumpcap -D (prefer exact match; fallback to contains)
Write-Log "Resolving interface via dumpcap -D ..."
$interfaces = & $DumpcapPath -D 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Log "ERROR: dumpcap -D failed: $interfaces"
  throw "dumpcap -D failed"
}

# dumpcap -D format: "1. \Device\NPF_{GUID} (Friendly Name)"
$ifaceLine = $interfaces | Where-Object { $_ -match [regex]::Escape($InterfaceMatch) } | Select-Object -First 1
if (-not $ifaceLine) {
  Write-Log "Could not find an interface containing: $InterfaceMatch"
  Write-Log "Available interfaces:"
  $interfaces | ForEach-Object { Write-Log "  $_" }
  throw "Interface not found"
}

# Extract the left side token after the index and space; keep the raw NPF device path if present
# Examples:
#   7. \Device\NPF_{A1B2...} (vEthernet (nat))
#   13. rpcap://\Device\NPF_{...} (some remote)
$iface =
  if ($ifaceLine -match '^\s*\d+\.\s+([^\s]+)\s+\(') { $matches[1] } else { $InterfaceMatch }

Write-Log "Resolved interface: $iface"
if ($CaptureFilter) { Write-Log "Using BPF filter: $CaptureFilter" } else { Write-Log "No BPF filter" }

# Build command: dumpcap -> stdout (binary) | ssh user@host "cat > /path"
# Use cmd.exe pipeline to avoid PowerShell text encoding issues with binary streams.
$dumpArgs = @("-i", $iface, "-w", "-") + $(if ($CaptureFilter) { @("-f", $CaptureFilter) } else { @() })
$sshRemote = "$RemoteUser@$RemoteHost"
$sshCmd    = "cat > " + ($RemotePath -replace '"','\"')

# Compose a single cmd.exe line with quoted paths/args
# Example:
#   "C:\Program Files\Wireshark\dumpcap.exe" -i \Device\NPF_{GUID} -f "tcp port 443" -w - | "C:\Windows\System32\OpenSSH\ssh.exe" -o BatchMode=yes user@host "cat > /tmp/file.pcap"
$dumpExeQ = '"' + $DumpcapPath + '"'
$sshExeQ  = '"' + $SshPath + '"'
$dumpArgStr = ($dumpArgs | ForEach-Object {
  if ($_ -match '\s') { '"' + ($_ -replace '"','\"') + '"' } else { $_ }
}) -join ' ' 
$cmdLine = "$dumpExeQ $dumpArgStr | $sshExeQ -o BatchMode=yes $sshRemote `"${sshCmd}`""

Write-Log "Pipeline: $cmdLine"

# Main loop: restart on failure
while ($true) {
  try {
    Write-Log "Starting capture pipeline..."
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c $cmdLine" -NoNewWindow -PassThru
    $proc.WaitForExit()
    $code = $proc.ExitCode
    Write-Log "Capture exited with code $code"
  } catch {
    Write-Log "Exception: $($_.Exception.Message)"
  }
  Write-Log "Sleeping $ReconnectDelay seconds before retry..."
  Start-Sleep -Seconds $ReconnectDelay
}
