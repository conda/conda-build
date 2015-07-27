if not exist .git exit 1
git describe
if errorlevel 1 exit 1
for /f "delims=" %%i in ('git describe') do set gitdesc=%%i
if errorlevel 1 exit 1
echo "%gitdesc%"
if not "%gitdesc%"=="1.8.1" exit 1
git status
if errorlevel 1 exit 1
set PYTHONPATH=.
python -c "import conda_build; assert conda_build.__version__ == '1.8.1', conda_build.__version__"
if errorlevel 1 exit 1
