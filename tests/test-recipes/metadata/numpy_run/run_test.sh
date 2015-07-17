conda list -p $PREFIX --canonical
# Test the build string. Should contian NumPy, but not the version
conda list -p $PREFIX --canonical | grep "conda-build-test-numpy-run-1\.0-nppy.._0"

cat $PREFIX/conda-meta/conda-build-test-numpy-run-1.0-nppy*_0.json
cat $PREFIX/conda-meta/conda-build-test-numpy-run-1.0-nppy*_0.json | grep 'numpy'
cat $PREFIX/conda-meta/conda-build-test-numpy-run-1.0-nppy*_0.json | grep -v 'numpy .\..\*'
