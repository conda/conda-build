conda list -p $PREFIX --canonical
# Test the build string. Should contain Numpy
conda list -p $PREFIX --canonical | grep "conda-build-test-numpy-build-xx-1.0-0"
