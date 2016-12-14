# test copying filename
echo "weee" > $PREFIX/subpackage_file1
# test copying by folder name
mkdir $PREFIX/somedir
echo "weee" > $PREFIX/somedir/subpackage_file1
# test glob patterns
echo "weee" > $PREFIX/subpackage_file1.ext
echo "weee" > $PREFIX/subpackage_file2.ext
