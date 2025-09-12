@echo off
rem This runs at the END of the automated Windows install inside dockur/windows.

:: Copy the script we want to run every boot to a stable path
copy /Y "C:\OEM\install.bat" "C:\OEM\install-on-boot.cmd"

:: Create/replace a Startup task that runs as SYSTEM at every boot
schtasks /Create /F ^
  /TN "PQBench-InstallAtBoot" ^
  /TR "cmd /C C:\OEM\install-on-boot.cmd" ^
  /SC ONSTART ^
  /RU "SYSTEM"

rem 1) Enable PowerShell script execution for our bootstrap
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\OEM\StartKyber.ps1"