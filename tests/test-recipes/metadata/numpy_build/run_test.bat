:: show list
conda list -p "%PREFIX%" --canonical
if errorlevel 1 exit 1

:: grep for package
conda list -p "%PREFIX%" --canonical | grep "conda-build-test-numpy-build-1.0-0"
if errorlevel 1 exit 1
