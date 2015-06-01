conda list -p "%PREFIX%" --canonical
if errorlevel 1 exit 1
for /f "delims=" %%i in ('conda list -p "%PREFIX%" --canonical') do set condalist=%%i
if errorlevel 1 exit 1
echo "%condalist%"
if not "%condalist%"=="conda-build-test-build-string-1.0-abc" exit 1
cat "%PREFIX%\conda-meta\conda-build-test-build-string-1.0-abc.json"
if errorlevel 1 exit 1
cat "%PREFIX%\conda-meta\conda-build-test-build-string-1.0-abc.json" | grep '"build_number": 0'
if errorlevel 1 exit 1
cat "%PREFIX%\conda-meta\conda-build-test-build-string-1.0-abc.json" | grep '"build": "abc"'
if errorlevel 1 exit 1
