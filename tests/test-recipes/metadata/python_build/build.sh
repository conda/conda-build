if [ -z "${STDLIB_DIR:-}" ]; then
    echo "STDLIB_DIR is unset";
    exit 1
fi

if [ -z "${SP_DIR:-}" ]; then
    echo "SP_DIR is unset";
    exit 1
fi
