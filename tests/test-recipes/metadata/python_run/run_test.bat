conda list -p "%PREFIX%" --canonical
if errorlevel 1 exit 1
for /f "delims=" %%i in ('conda list -p "%PREFIX%" --canonical') do set condalist=%%i
if errorlevel 1 exit 1
echo "%condalist%"
if not "%condalist%"=="conda-build-test-python-run-1.0-0" exit 1
cat "%PREFIX%\conda-meta\conda-build-test-python-run-1.0-0.json"
if errorlevel 1 exit 1
cat "%PREFIX%\conda-meta\conda-build-test-python-run-1.0-0.json" | grep -v 'python'
if errorlevel 1 exit 1
