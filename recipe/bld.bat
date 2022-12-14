python setup.py install --single-version-externally-managed --record=record.txt
IF %ERRORLEVEL% NEQ 0 exit 1

del %SCRIPTS%\conda-init
