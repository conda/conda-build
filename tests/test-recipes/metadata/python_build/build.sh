if [ -z "${STDLIB_DIR:-}" ]; then
    echo "STDLIB_DIR is unset";
    exit 1
elif [[ ${STDLIB_DIR} =~ '.*python3\.(1|2)$' ]]; then
    echo "STDLIB_DIR is set to wrong path: $STDLIB_DIR"
    exit 1
else
    echo "STDLIB_DIR is set to $STDLIB_DIR";
    echo "STDLIB_DIR has $(ls -l $STDLIB_DIR | wc -l) lines"
fi

if [ -z "${SP_DIR:-}" ]; then
    echo "SP_DIR is unset";
    exit 1
else
    echo "SP_DIR is set to $SP_DIR";
    echo "SP_DIR has $(ls -l $SP_DIR | wc -l) lines"
fi
