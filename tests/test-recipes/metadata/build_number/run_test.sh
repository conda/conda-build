conda list -p $PREFIX --canonical
# This is actually the build string. We test the build number below, the variant without
# 'local::' is for conda <4.1 and could be removed in the future.
[ "$(conda list -p $PREFIX --canonical)" = "conda-build-test-build-number-1.0-1" ] || \
[ "$(conda list -p $PREFIX --canonical)" = "local::conda-build-test-build-number-1.0-1" ]

cat $PREFIX/conda-meta/conda-build-test-build-number-1.0-1.json
cat $PREFIX/conda-meta/conda-build-test-build-number-1.0-1.json | grep '"build_number": 1'
