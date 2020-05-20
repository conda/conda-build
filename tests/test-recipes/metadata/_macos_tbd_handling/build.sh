#!/bin/bash

[[ -d ${PREFIX}/bin ]] || mkdir ${PREFIX}/bin
[[ -d ${PREFIX}/lib ]] || mkdir ${PREFIX}/lib
export LDFLAGS=$(echo "${LDFLAGS}" | sed "s/-Wl,-dead_strip_dylibs//g")
${CC} ${CFLAGS} ${LDFLAGS} -framework CoreFoundation -o ${PREFIX}/bin/hello_world -x c hello-world.c
