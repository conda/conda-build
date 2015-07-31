@echo on
@rem No if errorlevel 1 exit 1's here to make sure the recipe fails from the
@rem conda-build check.
if not exist "%PREFIX%\conda-meta" mkdir "%PREFIX%\conda-meta"
echo. > "%PREFIX%\conda-meta\nope"
