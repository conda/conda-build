#!/bin/bash

echo "int main() { return 0; }" | ${CC} ${CFLAGS} ${LDFLAGS} -o ${PREFIX}/bin/overlinking -lbz2 -x c -
