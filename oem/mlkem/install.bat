@echo off
setlocal
set "LOG=C:\OEM\install.log"

>>"%LOG%" echo ==== install.bat START %DATE% %TIME% ====

copy /Y "C:\OEM\install.bat" "C:\OEM\install-on-boot.cmd" >>"%LOG%" 2>&1
schtasks /Create /F ^
  /TN "PQBench-InstallAtBoot" ^
  /TR "cmd /C C:\OEM\install-on-boot.cmd" ^
  /SC ONSTART ^
  /RU SYSTEM >>"%LOG%" 2>&1

rem 1) Enable PowerShell script execution for our bootstrap
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\OEM\StartMLKEM.ps1" >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"

>>"%LOG%" echo ==== install.bat END %DATE% %TIME% RC=%RC% ====
endlocal & exit /b %RC%