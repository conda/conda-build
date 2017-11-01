rem this tests an issue where the prefix folder structure was captured into
rem packages, and the later occurrence was being replaced in conda-builds notion,
rem but not on disk. It should have only been getting replaced for the first
rem instance, to obtain a relative path.

rem this test creates a file in such a path, and triggers the behavior
mkdir %PREFIX%\include\%PREFIX%
echo 'weeee' > %PREFIX%\include\%PREFIX%\test
