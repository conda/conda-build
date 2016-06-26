cd %RECIPE_DIR%..\..\test-package
python setup.py install
if errorlevel 1 exit 1
