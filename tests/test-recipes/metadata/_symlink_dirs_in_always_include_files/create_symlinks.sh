mkdir -p $PREFIX/sysroot/lib64
touch $PREFIX/sysroot/lib64/empty
ln -s $PREFIX/sysroot/lib64 $PREFIX/sysroot/lib
