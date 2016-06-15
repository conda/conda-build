conda list -p $PREFIX --canonical
# This is actually the build string. We test the build number below
[ "$(conda list -p $PREFIX --canonical)" = "local::conda-build-test-build-string-1.0-abc" ]

cat $PREFIX/conda-meta/conda-build-test-build-string-1.0-abc.json
cat $PREFIX/conda-meta/conda-build-test-build-string-1.0-abc.json | grep '"build_number": 0'
cat $PREFIX/conda-meta/conda-build-test-build-string-1.0-abc.json | grep '"build": "abc"'
