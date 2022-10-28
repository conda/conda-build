:: This one is noarch: python so conda creates the entry points.
%CONDA_PREFIX%\Scripts\test_entry_points_have_prefix_CASED.exe
if %ErrorLevel% NEQ 0 exit /b 1
exit /b 0
