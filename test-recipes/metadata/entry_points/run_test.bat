rem Won't be found because there are no shebang lines on Windows

rem python test-script-setup.py
rem if errorlevel 1 exit 1
rem python test-script-setup.py | grep "Test script setup\.py"

test-script-manual
if errorlevel 1 exit 1
test-script-manual | grep "Manual entry point"
