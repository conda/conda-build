#!/bin/bash

# this recipe will overlink libraries without the --as-needed linker arg
re='^(.*)-Wl,--as-needed(.*)$'
if [[ ${LDFLAGS} =~ $re ]]; then
    export LDFLAGS="${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
fi

autoreconf -vfi
mkdir build-${HOST} && pushd build-${HOST}
${SRC_DIR}/configure --prefix=${PREFIX}  \
          --with-zlib         \
          --with-bz2lib       \
          --with-iconv        \
          --with-lz4          \
          --with-lzma         \
          --with-lzo2         \
          --without-cng       \
          --with-openssl      \
          --without-nettle    \
          --with-xml2         \
          --without-expat
make -j${CPU_COUNT} ${VERBOSE_AT}
make install
popd
