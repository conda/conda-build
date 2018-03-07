find $SRC_DIR -type f
if [[ ! -f "$SRC_DIR/mypkg/awesomeheader.h" ]]; then
    exit 1
fi

# when a file shadows the parent directory name
if [[ ! -f "$SRC_DIR/mypkg/mypkg" ]]; then
    exit 1
fi

echo "found source files OK"
exit 0
