where cl.exe
where link.exe
:: maybe informative for MinGW?
where gcc.exe

cmake -G "%CMAKE_GENERATOR:"=%" "%RECIPE_DIR%"
cmake --build . --config Release
