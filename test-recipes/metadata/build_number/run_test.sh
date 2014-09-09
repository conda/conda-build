conda list -p $PREFIX --canonical
[ "$(conda list -p $PREFIX --canonical)" = "conda-build-test-build-number-1.0-1" ]
