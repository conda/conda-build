@echo on
echo #include ^<bzlib.h^>>main.c
echo int main() { BZ2_bzlibVersion(); return 0; }>>main.c
cl -c -EHsc -GR -Zc:forScope -Zc:wchar_t -Fomain.obj main.c -INCLUDE:%PREFIX%\Library\include
link -out:%PREFIX%\Library\bin\main.exe main.obj -LIBPATH:%PREFIX%\Library\lib bzip2.lib
