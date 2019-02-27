#!/usr/bin/env bash

curl -SLO https://raw.githubusercontent.com/python/cpython/3.7/PC/launcher.c -O launcher.c
patch -p0 < $(dirname ${BASH_SOURCE[0]})/cpython-launcher-c-mods-for-setuptools.3.7.patch
RCFILE=$(dirname ${BASH_SOURCE[0]})/resources.rc
[[ -f ${RCFILE} ]] && rm -f ${RCFILE}
echo "#include \"winuser.h\""      > ${RCFILE}
echo "1 RT_MANIFEST manifest.xml" >> ${RCFILE}
for _BITS in 64 32; do
  [[ -f resources-${_BITS}.res ]] && rm -f resources-${_BITS}.res
  PATH=/mingw${_BITS}/bin:$PATH windres --input ${RCFILE} --output resources-${_BITS}.res --output-format=coff
  for _TYPE in cli gui; do
    if [[ ${_TYPE} == cli ]]; then
      CPPFLAGS=
      LDFLAGS=
    else
      CPPFLAGS="-D_WINDOWS -mwindows"
      LDFLAGS="-mwindows"
    fi
    # You *could* use MSVC 2008 here, but you'd end up with much larger (~230k) executables.
    # cl.exe -opt:nowin98 -D NDEBUG -D "GUI=0" -D "WIN32_LEAN_AND_MEAN" -ZI -Gy -MT -MERGE launcher.c -Os -link -MACHINE:x64 -SUBSYSTEM:CONSOLE version.lib advapi32.lib shell32.lib
    PATH=/mingw${_BITS}/bin:$PATH gcc -O2 -DSCRIPT_WRAPPER -DUNICODE -D_UNICODE -DMINGW_HAS_SECURE_API ${CPPFLAGS} launcher.c -c -o ${_TYPE}-${_BITS}.o
    PATH=/mingw${_BITS}/bin:$PATH gcc -Wl,-s --static -static-libgcc -municode ${LDFLAGS} ${_TYPE}-${_BITS}.o resources-${_BITS}.res -o ${_TYPE}-${_BITS}.exe
  done
done
ls -l *.exe
echo "Debug this from cmd.exe via:"
echo "set PYLAUNCH_DEBUG=1"
