#!/bin/bash

[[ -d ${PREFIX}/bin ]] || mkdir ${PREFIX}/bin
${CC} ${CFLAGS} ${LDFLAGS} -o ${PREFIX}/bin/hello_world -x c hello-world.c
