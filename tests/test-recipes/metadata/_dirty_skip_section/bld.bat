:: ensure that the DIRTY environment variable is available for logic in build scripts
IF "%DIRTY%" == "1" exit 0
exit 1