conda list -p $PREFIX --canonical
# Test the build string. Should not contain Numpy
conda list -p $PREFIX --canonical | grep "conda-build-test-numpy-build-1.0-0"
