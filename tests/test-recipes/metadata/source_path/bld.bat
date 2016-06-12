rem If directory exists, we did it right
cd tests/test-recipes/test-package
if errorlevel 1 exit 1


rem check that GIT_* tags are present
for %%i in (GIT_DESCRIBE_TAG GIT_DESCRIBE_NUMBER GIT_DESCRIBE_HASH GIT_FULL_HASH) DO (
  if defined %%i (
      echo %%i
  ) else (
    exit 1
  )
)
