python setup.py install --single-version-externally-managed --record=record.txt
IF %ERRORLEVEL% NEQ 0 exit 1

del %SCRIPTS%\conda-init

copy bdist_conda.py %PREFIX%\Lib\distutils\command\
IF %ERRORLEVEL% NEQ 0 exit 1

:: required for distutils included in setuptools >=60.0.0
:: see also https://setuptools.pypa.io/en/latest/history.html#v60-0-0
set "SETUPTOOLS_DISTUTILS="%PREFIX%\Lib\site-packages\setuptools\_distutils\command\"
mkdir "%SETUPTOOLS_DISTUTILS%"
copy bdist_conda.py "%SETUPTOOLS_DISTUTILS%"
IF %ERRORLEVEL% NEQ 0 exit 1
