mkdir -p $PREFIX/test
echo "echo weee" > $PREFIX/test/weee
chmod +x $PREFIX/test/weee

mkdir -p $PREFIX/bin
# bin script is just a link
ln -s $PREFIX/test/weee $PREFIX/bin/weee

# link to folder itself
ln -s $PREFIX/test $PREFIX/test_link
