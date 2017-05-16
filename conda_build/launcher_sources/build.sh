#!/usr/bin/env bash

wget -c https://raw.githubusercontent.com/python/cpython/3.6/PC/launcher.c -O launcher.c
patch -p0 < $(dirname ${BASH_SOURCE[0]})/cpython-launcher-c-mods-for-setuptools.patch
PATH=/mingw64/bin:$PATH gcc -mconsole -O2 -Wl,-s -DSCRIPT_WRAPPER -DUNICODE -D_UNICODE -DMINGW_HAS_SECURE_API launcher.c -lversion --static -static-libgcc -o cli-64.exe
PATH=/mingw32/bin:$PATH gcc -mconsole -O2 -Wl,-s -DSCRIPT_WRAPPER -DUNICODE -D_UNICODE -DMINGW_HAS_SECURE_API launcher.c -lversion --static -static-libgcc -o cli-32.exe
PATH=/mingw64/bin:$PATH gcc -mwindows -municode -O2 -Wl,-s -DSCRIPT_WRAPPER -DUNICODE -D_UNICODE -D_WINDOWS -DMINGW_HAS_SECURE_API launcher.c -lversion --static -static-libgcc -o gui-64.exe
PATH=/mingw32/bin:$PATH gcc -mwindows -municode -O2 -Wl,-s -DSCRIPT_WRAPPER -DUNICODE -D_UNICODE -D_WINDOWS -DMINGW_HAS_SECURE_API launcher.c -lversion --static -static-libgcc -o gui-32.exe
ls -l *.exe
echo "Debug this from cmd.exe via:"
echo "set PYLAUNCH_DEBUG=1"
