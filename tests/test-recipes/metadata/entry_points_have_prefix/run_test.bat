
%CONDA_PREFIX%\Scripts\test_entry_points_have_prefix_CASED.exe
:: On Windows we expect the (binary) file to contain '_h_env' since we do not replace prefixes and so
:: we expect this (pip-generated) exe to fail with something like:
:: Fatal error in launcher: Unable to create process using
::   '"c:\opt\conda\conda-bld\entry_points_have_prefix-0.0.1\_h_env\python.exe"
::    "C:\opt\conda\conda-bld\entry_points_have_prefix-0.0.1\_test_env\Scripts\test_entry_points_have_prefix_CASED.exe" ':
::     The system cannot find the file specified.
if %ErrorLevel% EQU 0 goto ran_ok_thats_bad
rg --with-filename "_h_env" %CONDA_PREFIX%\Scripts\test_entry_points_have_prefix_CASED.exe
if %ErrorLevel% NEQ 0 goto didnt_find_h_env_thats_bad
exit /b 0
:didnt_find_h_env_thats_bad
echo ERROR :: Expected %CONDA_PREFIX%\Scripts\test_entry_points_have_prefix_CASED.exe to contain "_h_env". It did not.
echo ERROR :: This suggests binary prefix replacement is being performed on Windows by default.
exit /b 1
:ran_ok_thats_bad
echo ERROR :: Ran test_entry_points_have_prefix_CASED.exe just fine. That should not have worked since pip emits
echo ERROR :: python executables with full paths into its stub executables and we do not do binary_prefix_replacement
echo ERROR :: on Windows (by default as we cannot install into the long paths that this requires).
exit /b 1
