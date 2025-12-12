bsdtar -xf sleef-3.7-h7e360cc_0.conda
bsdtar -xf pkg-sleef-3.7-h7e360cc_0.tar.zst
mkdir %LIBRARY_BIN%
mkdir %BUILD_PREFIX%\etc\conda-build\dsolists.d
copy %RECIPE_DIR%\vc-dsolists.json %BUILD_PREFIX%\etc\conda-build\dsolists.d\vc-dso.json
copy Library\bin\sleef.dll %LIBRARY_BIN%
