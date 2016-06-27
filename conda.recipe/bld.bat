%PYTHON% setup.py install --single-version-externally-managed --record=record.txt
if errorlevel 1 exit 1

del %SCRIPTS%\conda-init
if errorlevel 1 exit 1

copy bdist_conda.py %PREFIX%\Lib\distutils\command\
if errorlevel 1 exit 1
