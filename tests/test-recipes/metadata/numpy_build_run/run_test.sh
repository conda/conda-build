conda list -p $PREFIX --canonical
# Test the build string. Should contain NumPy, but not the version
conda list -p $PREFIX --canonical | grep "conda-build-test-numpy-build-run-1\.0-py.._0"
