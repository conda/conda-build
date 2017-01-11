:: ensure that the DIRTY environment variable is available for logic in build scripts
echo DIRTY environment variable should be "1".  Is currently: "%DIRTY%"
IF "%DIRTY%" == "1" exit 0
exit 1