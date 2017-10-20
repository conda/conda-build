if [ ! -f setup.py ]; then
    exit 1
else
    echo "found setup.py in workdir ($(pwd)) OK"
fi
