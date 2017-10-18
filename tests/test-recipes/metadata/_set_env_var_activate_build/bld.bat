echo TEST_VAR is "%TEST_VAR%" (should be "1")
if "%TEST_VAR%" == "" exit 1

echo VS90COMNTOOLS is "%VS90COMNTOOLS%" (should be some path to vs)
if "%VS90COMNTOOLS%" == "" exit 1