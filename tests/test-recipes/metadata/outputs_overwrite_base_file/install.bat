:: Always output 4 characters to properly test even if "SafetyError: ... incorrect size." is not triggered.
< nul set /p="%PKG_NAME:~0,4%" > "%PREFIX%\file" & call;
