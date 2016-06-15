mkdir %PREFIX%\etc\conda\activate.d
echo set TEST_VAR=1 > %PREFIX%\etc\conda\activate.d\test.bat

mkdir %PREFIX%\etc\conda\deactivate.d
echo set TEST_VAR= > %PREFIX%\etc\conda\deactivate.d\test.bat
