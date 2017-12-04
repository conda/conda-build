set -ex

if [ "$(uname)" == "Darwin" ]; then
    test -e $PREFIX/lib/libz.dylib
    test -e $PREFIX/lib/libjpeg.dylib
else
    test -e $PREFIX/lib/libz.so
    test -e $PREFIX/lib/libjpeg.so
fi
