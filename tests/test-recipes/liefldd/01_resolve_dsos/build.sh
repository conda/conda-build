echo "PWD is $PWD"
ls -l ${PREFIX}
${CC} -c ${LDFLAGS} ${CFLAGS} -o foo/main.o foo/main.c
${CC} -c ${LDFLAGS} ${CFLAGS} -o bar/main.o bar/main.c
${CC} -shared -o foo/libmain.so foo/main.o
${CC} -shared -o bar/libmain.so bar/main.o
${CC} -o foo_exe foobar.c -Lfoo -lmain -Wl,-rpath,'$ORIGIN/foo'
${CC} -o bar_exe foobar.c -Lbar -lmain -Wl,-rpath,'$ORIGIN/bar'
./foo_exe | grep foo
./bar_exe | grep bar
cp foo_exe ${PREFIX}/
cp bar_exe ${PREFIX}/
ls -l ${PREFIX}
# No idea what's created foo and bar already.
mkdir ${PREFIX}/foo
mkdir ${PREFIX}/bar
cp foo/libmain.so ${PREFIX}/foo/
cp bar/libmain.so ${PREFIX}/bar/
