conda list -p $PREFIX --canonical
# Test the build string. Should contain Python
conda list -p $PREFIX --canonical | grep "conda-build-test-python-build-run-1\.0-py.._0"

cat $PREFIX/conda-meta/conda-build-test-python-build-run-1.0-py*_0.json
cat $PREFIX/conda-meta/conda-build-test-python-build-run-1.0-py*_0.json | grep 'python .\..\*'
