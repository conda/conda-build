#!/bin/bash

rm -f ${PREFIX}/lib/libz*{.dylib,.so} || true
echo "#include <stdio.h>\n#include <zlib.h>\nint main() {\n  const char * zlv = zlibVersion();\n  printf(\"zlibVersion=%s\n\", zlv);\nreturn 0;\n}\n" | ${CC} ${CFLAGS} ${LDFLAGS} -o ${PREFIX}/bin/c_vendoring -lz -x c 
