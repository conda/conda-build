set -ex

cd $SRC_DIR

if [ ! -f setup.py ]; then
    ls
    echo $(pwd)
    exit 1
else
    echo "found setup.py in workdir ($(pwd)) OK"
fi
