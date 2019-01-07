set NLM=^


set NL=^^^%NLM%%NLM%^%NLM%%NLM%
echo on
echo #include ^<stdio.h^>%NL%#include ^<zlib.h^>%NL%int main() {%NL%  const char * zlv = zlibVersion();%NL%  printf("zlibVersion=%%s\n", zlv);%NL%  return 0;%NL%}%NL%> zlibVersion.c
cl.exe -nologo %CFLAGS% -I %LIBRARY_PREFIX%\include -c zlibVersion.c
link.exe -nologo zlibVersion.obj -libpath:%LIBRARY_PREFIX%\lib zlibstatic.lib -NODEFAULTLIB:msvcrt -out:%LIBRARY_PREFIX%\bin\zlibVersion.exe
%LIBRARY_PREFIX%\bin\zlibVersion.exe
