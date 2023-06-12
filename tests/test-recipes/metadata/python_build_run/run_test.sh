# show list
conda list -p "$PREFIX" --canonical

# grep for package
conda list -p "$PREFIX" --canonical | grep "conda-build-test-python-build-run-1.0-py.*_0"
