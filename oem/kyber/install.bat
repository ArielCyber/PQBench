@echo off
rem This runs at the END of the automated Windows install inside dockur/windows.

rem 1) Enable PowerShell script execution for our bootstrap
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\OEM\StartKyber.ps1"
