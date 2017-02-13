conda list -p "%PREFIX%" --canonical
if errorlevel 1 exit 1
conda list -p "%PREFIX%" --canonical | grep "conda-build-test-python-run-1\.0-h......._0"
if errorlevel 1 exit 1
