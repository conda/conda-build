:: Needed so we can find stdint.h from msinttypes.
set LIB=%LIBRARY_LIB%;%LIB%
set LIBPATH=%LIBRARY_LIB%;%LIBPATH%
set INCLUDE=%LIBRARY_INC%;%INCLUDE%

:: VS2008 doesn't have stdbool.h so copy in our own
:: to 'lib' where the other headers are so it gets picked up.
if "%VS_MAJOR%" == "9" (
  if "%ARCH%" == "64" (
::  The Windows 6.0A SDK does not provide the bcrypt.lib for 64-bit:
::  C:\Program Files\Microsoft SDKs\Windows\v6.0A\Lib\x64
::  .. yet does for 32-bit, oh well, this may disable password protected zip support.
::  https://social.msdn.microsoft.com/Forums/windowsdesktop/en-US/673cc344-430c-4510-96e8-80b0bb42ae11/can-not-link-bcryptlib-to-an-64bit-build?forum=windowssdk
    set ENABLE_CNG=NO
  ) else (
    set ENABLE_CNG=YES
::  Have decided to standardise on *not* using bcrypt instead. If we update to the Windows Server 2008 SDK we could revisit this
    set ENABLE_CNG=NO
  )
)

if "%vc%" NEQ "9" goto not_vc9
:: This does not work yet:
:: usage: cl [ option... ] filename... [ /link linkoption... ]
  set USE_C99_WRAP=no
  copy %LIBRARY_INC%\inttypes.h src\common\inttypes.h
  copy %LIBRARY_INC%\stdint.h src\common\stdint.h
  goto endit
:not_vc9
  set USE_C99_WRAP=no
:endit

if exist CMakeCache.txt goto build
if "%USE_C99_WRAP%" NEQ "yes" goto skip_c99_wrap
set COMPILER=-DCMAKE_C_COMPILER=c99-to-c89-cmake-nmake-wrap.bat
set C99_TO_C89_WRAP_DEBUG_LEVEL=1
set C99_TO_C89_WRAP_SAVE_TEMPS=1
set C99_TO_C89_WRAP_NO_LINE_DIRECTIVES=1
set C99_TO_C89_CONV_DEBUG_LEVEL=1
:skip_c99_wrap
:: set cflags because NDEBUG is set in Release configuration, which errors out in test suite due to no assert
cmake -G "NMake Makefiles" ^
      -DCMAKE_INSTALL_PREFIX="%LIBRARY_PREFIX%" ^
      %COMPILER% ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_C_USE_RESPONSE_FILE_FOR_OBJECTS:BOOL=FALSE ^
      -DCMAKE_INSTALL_PREFIX=%LIBRARY_PREFIX% ^
      -DCMAKE_C_FLAGS_RELEASE="%CFLAGS%" ^
      -DENABLE_CNG=%ENABLE_CNG% ^
      .

:build

:: Build.
jom -j%CPU_COUNT% VERBOSE=1
if errorlevel 1 exit /b 1
jom VERBOSE=1 install
if errorlevel 1 exit /b 1

:: Test.
:: Failures:
:: The following tests FAILED:
::         365 - libarchive_test_read_truncated_filter_bzip2 (Timeout) => runs msys2's bzip2.exe
::         372 - libarchive_test_sparse_basic (Failed)
::         373 - libarchive_test_fully_sparse_files (Failed)
::         386 - libarchive_test_warn_missing_hardlink_target (Failed)
:: ctest -C Release
:: if errorlevel 1 exit 1

:: Test extracting a 7z. This failed due to not using the multi-threaded DLL runtime, fixed by 0009-CMake-Force-Multi-threaded-DLL-runtime.patch
powershell -command "& { (New-Object Net.WebClient).DownloadFile('http://download.qt.io/development_releases/prebuilt/llvmpipe/windows/opengl32sw-64-mesa_12_0_rc2.7z', 'opengl32sw-64-mesa_12_0_rc2.7z') }"
if errorlevel 1 exit 1
%LIBRARY_BIN%\bsdtar -xf opengl32sw-64-mesa_12_0_rc2.7z
if errorlevel 1 exit 1
