if [[ -z "$CC" ]]; then
  conda activate $BUILD_PREFIX
fi
echo "int main() {}" > main.c
mkdir -p $PREFIX/bin
$CC main.c -o $PREFIX/bin/_file_hash

echo "int foo() {return 2;}" > foo.c
echo "int foo(); int bar() {return foo()*2;}" > bar.c
$CC -shared foo.c -o libupstream.so
$CC -shared bar.c -o libdownstream.so -L$PWD -lupstream '-Wl,-rpath,$ORIGIN'
