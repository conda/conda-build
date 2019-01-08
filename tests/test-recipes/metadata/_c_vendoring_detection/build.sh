#!/bin/bash

rm -f ${PREFIX}/lib/libz*{.dylib,.so}* || true
echo -e '#include <stdio.h>\n#include <zlib.h>\nint main(int argc, char const * argv[]) {\n  const char * zlv = zlibVersion();\n  printf("zlibVersion=%s", zlv);\n  return 0;\n}\n' | ${CC} ${CFLAGS} ${LDFLAGS} -o ${PREFIX}/bin/c_vendoring -I${PREFIX}/include -L${PREFIX}/lib -x c - -lz
