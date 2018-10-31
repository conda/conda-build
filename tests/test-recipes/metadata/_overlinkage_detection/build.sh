#!/bin/bash

[[ -d ${PREFIX}/bin ]] || mkdir ${PREFIX}/bin

${CC} ${CFLAGS} main.c -o ${PREFIX}/bin/overlinking
