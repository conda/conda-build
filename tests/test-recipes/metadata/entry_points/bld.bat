:: cd %RECIPE_DIR%\..\..\test-package
:: pip install --no-deps .
python setup.py install
if errorlevel 1 exit 1
