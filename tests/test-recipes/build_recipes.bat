cd %~dp0

REM Recipes that should fail and give some error

cd metadata

for /d /r %%F in (*) do (
    conda build --no-anaconda-upload %%F
    if errorlevel 1 exit /B
)

cd ..

echo "TESTS PASSED"
