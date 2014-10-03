rem We have to use the absolute path because there is no "shebang line" in Windows
python "%PREFIX%\Scripts\test-script-setup.py"
if errorlevel 1 exit 1
python "%PREFIX%\Scripts\test-script-setup.py" | grep "Test script setup\.py"
if errorlevel 1 exit 1

test-script-manual
if errorlevel 1 exit 1
test-script-manual | grep "Manual entry point"
if errorlevel 1 exit 1
