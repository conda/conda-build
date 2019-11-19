${CC} -c ${LDFLAGS} ${CFLAGS} -o foo/main.o foo/main.c
${CC} -c ${LDFLAGS} ${CFLAGS} -o bar/main.o bar/main.c
${CC} -shared -o foo/libmain.so.0 foo/main.o -Wl,-soname=libmain.so.0
${CC} -shared -o bar/libmain.so.0 bar/main.o -Wl,-soname=libmain.so.0
ln -s libmain.so.0 foo/libmain.so
ln -s libmain.so.0 bar/libmain.so
${CC} -o foo_exe foobar.c -Lfoo -lmain -Wl,-rpath,'$ORIGIN/foo'
${CC} -o bar_exe foobar.c -Lbar -lmain -Wl,-rpath,'$ORIGIN/bar'
./foo_exe | grep foo
./bar_exe | grep bar
mkdir ${PREFIX}/foo
mkdir ${PREFIX}/bar
cp --preserve=links foo/libmain.so* ${PREFIX}/foo/
cp --preserve=links bar/libmain.so* ${PREFIX}/bar/
cp foo_exe ${PREFIX}/
cp bar_exe ${PREFIX}/
