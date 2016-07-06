mkdir %PREFIX%\etc\conda\activate.d
:: output something so it's more obvious when scripts are running
echo "echo setting TEST_VAR" > %PREFIX%\etc\conda\activate.d\test.bat
echo set TEST_VAR=1 > %PREFIX%\etc\conda\activate.d\test.bat

mkdir %PREFIX%\etc\conda\deactivate.d
echo "echo setting TEST_VAR" > %PREFIX%\etc\conda\deactivate.d\test.bat
echo set TEST_VAR= > %PREFIX%\etc\conda\deactivate.d\test.bat
