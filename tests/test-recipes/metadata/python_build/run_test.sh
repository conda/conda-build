conda list -p $PREFIX --canonical
# Test the build string. Should not contain Python
[ "$(conda list -p $PREFIX --canonical)" = "conda-build-test-python-build-1.0-0" ]

cat $PREFIX/conda-meta/conda-build-test-python-build-1.0-0.json
cat $PREFIX/conda-meta/conda-build-test-python-build-1.0-0.json | grep -v 'python'
