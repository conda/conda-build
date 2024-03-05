## Always output 4 characters to properly test even if "SafetyError: ... incorrect size." is not triggered.
printf '%.4s' "${PKG_NAME}" > "${PREFIX}/file"
