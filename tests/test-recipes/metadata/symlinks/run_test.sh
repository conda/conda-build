# the real file
sh $PREFIX/test/weee

# the symlink to the file
sh $PREFIX/bin/weee
if [ ! -L $PREFIX/bin/weee ]; then
    echo "file in package is not a symlink"
    exit 1
fi

# the symlink to the folder
sh $PREFIX/test_link/weee
if [ ! -L $PREFIX/test_link ]; then
    echo "folder in package is not a symlink"
    exit 1
fi
