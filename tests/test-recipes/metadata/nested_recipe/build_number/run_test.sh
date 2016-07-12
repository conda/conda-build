conda list -p $PREFIX --canonical
# This is actually the build string. We test the build number below
[ "$(conda list -p $PREFIX --canonical)" = "local::conda-build-test-build-number-1.0-1" ]

cat $ROOT/conda-meta/conda-build-test-build-number-1.0-1.json
cat $ROOT/conda-meta/conda-build-test-build-number-1.0-1.json | grep '"build_number": 1'
