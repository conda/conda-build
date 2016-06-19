@echo ON

IF %DISTUTILS_USE_SDK% NEQ 1 ( EXIT 1 )
IF %MSSdk% NEQ 1 ( EXIT 1 )
IF NOT "%VS_VERSION%" == "%CONDATEST_MSVC_VER%" ( EXIT 1 )
IF NOT "%PY_VER%" == "2.7" ( EXIT 1 )

REM Run cl.exe to find which version our compiler is
REM    First picks out the version line
for /f "delims=" %%A in ('cl /? 2^>^&1 ^| findstr /C:"Version"') do set "CL_TEXT=%%A"
REM    Looks for the known version in that version line
echo %CL_TEXT% | findstr /C:"Version %CL_EXE_VERSION%" > nul && goto FOUND
REM only falls through here if things don't match
EXIT 1
:FOUND
exit 0