# show list
conda list -p "$PREFIX" --canonical

# grep for package
conda list -p "$PREFIX" --canonical | grep "conda-build-test-numpy-build-1.0-0"
