@echo on
cl -c -EHsc -GR -Zc:forScope -Zc:wchar_t -Fomain.obj main.c
link -out:%PREFIX%\Library\bin\main.exe main.obj -LIBPATH:%PREFIX%\Library\lib zlib.lib
