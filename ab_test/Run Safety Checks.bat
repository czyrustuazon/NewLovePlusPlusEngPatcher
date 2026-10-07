@echo off
rem Double-click menu for the regression checks. Paths come from
rem ab_test\paths.local.ps1 (same as make.ps1).
setlocal
cd /d "%~dp0.."

:menu
echo.
echo  NLPP safety checks
echo  ------------------
echo   1  code.bin checks          (~15 s, no emulator)
echo   2  Smoke boot + crash replays (~1 min, opens an Azahar window)
echo   3  1 then 2
echo   4  Full test suite          (~15 s)
echo   5  Quit
echo.
choice /c 12345 /n /m "Pick 1-5: "
set PICK=%errorlevel%
if %PICK%==5 exit /b 0

set RESULT=0
if %PICK%==1 call :run checks
if %PICK%==2 call :run smoke
if %PICK%==3 (
    call :run checks
    if not errorlevel 1 call :run smoke
)
if %PICK%==4 call :run test

echo.
if %RESULT%==0 (
    echo  ==== PASS ====
) else (
    echo  ==== FAIL ==== scroll up for the reason
)
pause
goto menu

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "ab_test\make.ps1" %1
if errorlevel 1 set RESULT=1
exit /b %errorlevel%
