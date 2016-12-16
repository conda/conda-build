if not exist .git exit 1
git config core.fileMode false
if errorlevel 1 exit 1
git describe --tags --dirty
if errorlevel 1 exit 1
for /f "delims=" %%i in ('git describe') do set gitdesc=%%i
if errorlevel 1 exit 1
echo "%gitdesc%"
if not "%gitdesc%"=="1.20.2" exit 1
git status
if errorlevel 1 exit 1


rem check that GIT_* tags are present
for %%i in (GIT_DESCRIBE_TAG GIT_DESCRIBE_NUMBER GIT_DESCRIBE_HASH GIT_FULL_HASH) DO (
  if defined %%i (
      echo %%i
  ) else (
    exit 1
  )
)
