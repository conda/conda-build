cd %RECIPE_DIR%\..\..\test-package
pip install --no-deps .
if errorlevel 1 exit 1
