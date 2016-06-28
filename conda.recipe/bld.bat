pip install --no-deps .
if errorlevel 1 exit 1

del %SCRIPTS%\conda-init
if errorlevel 1 exit 1

copy bdist_conda.py %PREFIX%\Lib\distutils\command\
if errorlevel 1 exit 1
