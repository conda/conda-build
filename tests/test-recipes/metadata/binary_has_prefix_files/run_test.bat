cd "%PREFIX%"
cat binary-has-prefix
cat binary-has-prefix | grep "%PREFIX%"
if errorlevel 1 exit 1
