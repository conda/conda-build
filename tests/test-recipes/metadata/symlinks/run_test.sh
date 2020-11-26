echo "Running real file"
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

# make sure the symlink to nowhere is around
if [ ! -L $PREFIX/symlink_to_nowhere ]; then
    echo "symlink to nowhere is not there"
    exit 1
fi

# make sure if we make the file that is linked, it works
echo "hi" > $PREFIX/does_not_exist
cat $PREFIX/symlink_to_nowhere
if [[ `cat $PREFIX/symlink_to_nowhere` != "hi" ]]; then
    echo "symlink to nowhere is not linked properly"
    exit 1
fi
