cd %SRC_DIR%

if not exist setup.py (
    dir
    exit 1
    ) else (
    echo "found setup.py in workdir (%CD%) OK"
)