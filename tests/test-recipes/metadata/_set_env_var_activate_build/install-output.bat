echo VS90COMNTOOLS is "%VS90COMNTOOLS%" (should be some path to vs)
if "%VS90COMNTOOLS%" == "" exit 1

call "%PREFIX%\Scripts\activate.bat" "%PREFIX%"