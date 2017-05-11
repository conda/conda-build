:: cd %RECIPE_DIR%\..\..\test-package
:: pip install --no-deps .
python setup.py install --old-and-unmanageable
if errorlevel 1 exit 1
