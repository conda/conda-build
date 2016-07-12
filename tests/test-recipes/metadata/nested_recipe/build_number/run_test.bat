conda list -p "%PREFIX%" --canonical
if errorlevel 1 exit 1
for /f "delims=" %%i in ('conda list -p "%PREFIX%" --canonical') do set condalist=%%i
if errorlevel 1 exit 1
echo "%condalist%"
if not "%condalist%"=="conda-build-test-build-number-1.0-1" exit 1
cat "%ROOT%\conda-meta\conda-build-test-build-number-1.0-1.json"
if errorlevel 1 exit 1
cat "%ROOT%\conda-meta\conda-build-test-build-number-1.0-1.json" | grep '"build_number": 1'
if errorlevel 1 exit 1
