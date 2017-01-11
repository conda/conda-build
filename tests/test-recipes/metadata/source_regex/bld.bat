if not exist .git exit 1
git config core.fileMode false
if errorlevel 1 exit 1
git describe --tags --dirty
if errorlevel 1 exit 1
for /f "delims=" %%i in ('git describe') do set gitdesc=%%i
if errorlevel 1 exit 1
echo "%gitdesc%"
if not "%gitdesc%"=="1.21.0" exit 1
:: This looks weird, but it reflects accurately the meta.yaml in conda_build_test_recipe at 1.21.0 tag
echo "%PKG_VERSION%"
if not "%PKG_VERSION%"=="1.20.2" exit 1
