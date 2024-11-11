#!/bin/bash

mkdir -p ${PREFIX}/bin

# Delete the x86_64 libc.so.6 to make sure we find the powerpc libc.so.6
rm -f ${BUILD_PREFIX}/x86_64-conda-linux-gnu/sysroot/lib64/libc.so.6

${CC} ${CFLAGS} main.c -o ${PREFIX}/bin/sysroot-detection
