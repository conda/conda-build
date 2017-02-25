mkdir -p $PREFIX/test
echo "echo weee" > $PREFIX/test/weee
chmod +x $PREFIX/test/weee

mkdir -p $PREFIX/bin
ln -s $PREFIX/test/weee $PREFIX/bin/weee

ln -s $PREFIX/test $PREFIX/test_link
