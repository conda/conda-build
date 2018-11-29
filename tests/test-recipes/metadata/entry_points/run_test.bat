rem We have to use the absolute path because there is no "shebang line" in Windows
%PYTHON% "%PREFIX%\Scripts\test-script-setup.py"
if errorlevel 1 exit 1
%PYTHON% "%PREFIX%\Scripts\test-script-setup.py" | findstr "Test script setup" || (exit /b 1)
if errorlevel 1 exit 1

test-script-manual
if errorlevel 1 exit 1
test-script-manual | findstr "Manual entry point" || (exit /b 1)
if errorlevel 1 exit 1
