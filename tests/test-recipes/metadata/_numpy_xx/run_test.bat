@echo on
conda list -p "%PREFIX%" --canonical
if errorlevel 1 exit 1
conda list -p "%PREFIX%" --canonical | grep "conda-build-test-numpy-build-run-1\.0-np112py.._0"
if errorlevel 1 exit 1
