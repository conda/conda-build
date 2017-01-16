conda list -p $PREFIX --canonical
# Test the build string. Should contain Python
conda list -p $PREFIX --canonical | grep "conda-build-test-python-run-1\.0-py..h...._0"
