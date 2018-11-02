#!/bin/bash

PKGS="icu-uc icu-io"
if [[ ${target_platform} == osx-64 ]]; then
  ${CC} ${CFLAGS} -Wl,-dead_strip_dylibs $(pkg-config --cflags-only-I ${PKGS}) $(pkg-config --libs ${PKGS}) main.c -o ${PREFIX}/bin/overlinking
else
  ${CC} ${CFLAGS} -Wl,--as-needed $(pkg-config --cflags-only-I ${PKGS}) $(pkg-config --libs ${PKGS}) main.c -o ${PREFIX}/bin/overlinking
fi
