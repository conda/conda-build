find $SRC_DIR -type f
if [[ ! -f "$SRC_DIR/mypkg/awesomeheader.h" ]]; then
    exit 1
fi
echo "found source files OK"
exit 0
