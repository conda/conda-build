# test copying filename
echo "weee" > $PREFIX/subpackage_file1
# test copying by folder name
mkdir $PREFIX/somedir
echo "weee" > $PREFIX/somedir/subpackage_file1
# test glob patterns
echo "weee" > $PREFIX/subpackage_file1.ext
echo "weee" > $PREFIX/subpackage_file2.ext
echo "weee" > $PREFIX/subpackage_file3.ext

# The files used to test the two subpackages must be disjoint because they are
# coinstalled
# test copying filename
echo "weee" > $PREFIX/subpackage_include_exclude1
# test copying by folder name
mkdir $PREFIX/anotherdir
echo "weee" > $PREFIX/anotherdir/subpackage_include_exclude1
# test glob patterns
echo "weee" > $PREFIX/subpackage_include_exclude1.wav
echo "weee" > $PREFIX/subpackage_include_exclude2.wav
echo "weee" > $PREFIX/subpackage_include_exclude3.wav
mkdir $PREFIX/lib
echo "weee" > $PREFIX/lib/libdav1d.fake
