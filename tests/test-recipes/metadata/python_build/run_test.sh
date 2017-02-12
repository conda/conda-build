conda list -p $PREFIX --canonical
# Test the build string. Should not contain Python
conda list -p $PREFIX --canonical | grep "conda-build-test-python-build-1.0-h......._0"
