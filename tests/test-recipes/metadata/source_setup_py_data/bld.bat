if not exist .git exit 1
git config core.fileMode false
if errorlevel 1 exit 1
git describe --tags --dirty
if errorlevel 1 exit 1
for /f "delims=" %%i in ('git describe') do set gitdesc=%%i
if errorlevel 1 exit 1
echo "%gitdesc%"
if not "%gitdesc%"=="1.21.5" exit 1
echo "%PKG_VERSION%"
if not "%PKG_VERSION%"=="1.21.5" exit 1
git status
if errorlevel 1 exit 1
git diff
if errorlevel 1 exit 1
set PYTHONPATH=.
python -c "import conda_build; assert conda_build.__version__ == '1.21.5', conda_build.__version__"
if errorlevel 1 exit 1
