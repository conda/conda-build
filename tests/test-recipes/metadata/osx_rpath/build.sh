echo "void foo() {}" > foo.c

${CC:-clang} -shared foo.c -o libfoo.dylib
# Add rpaths repeatedly until there's no space left in the Mach-O header
for i in {1..1000}; do
  ${INSTALL_NAME_TOOL:-install_name_tool} -add_rpath ${SRC_DIR}/foo${i} libfoo.dylib || true
done
mkdir -p ${PREFIX}/lib
mv libfoo.dylib ${PREFIX}/lib/
