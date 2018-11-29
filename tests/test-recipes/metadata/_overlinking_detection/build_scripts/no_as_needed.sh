#!/bin/bash

# this recipe will overlink libraries without the --as-needed/-dead_strip_dylibs linker arg
re='^(.*)-Wl,--as-needed(.*)$'
if [[ ${LDFLAGS} =~ $re ]]; then
  export LDFLAGS="${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
fi
re='^(.*)-Wl,-dead_strip_dylibs(.*)$'
if [[ ${LDFLAGS} =~ $re ]]; then
  export LDFLAGS="${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
fi

echo "int main() { return 0; }" | ${CC} ${CFLAGS} ${LDFLAGS} -o ${PREFIX}/bin/overlinking -lbz2 -x c -
