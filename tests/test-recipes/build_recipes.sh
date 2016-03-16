#!/bin/bash

set -e
set -x

cd "$(dirname "${BASH_SOURCE[0]}")"

# These variables are defined solely for testing purposes,
# so they can be checked within build scripts
export CONDA_TEST_VAR="conda_test"
export CONDA_TEST_VAR_2="conda_test_2"

pushd metadata
for recipe in */; do
    if [[ $(ls -A "$recipe") ]]; then
        if [[ $recipe == _* ]]; then
            continue
        elif [[ $recipe =~ .*osx_is_app.* && $(uname) != "Darwin" ]]; then
            continue
        fi
        conda build --no-anaconda-upload $recipe
    fi
done
popd

# Recipes that should fail and give some error
cd fail

# We use 2>&1 as the error is printed to stderr. We could do >/dev/null to
# ensure it is printed to stderr, but then we would hide the output of the
# command from the test output.  The ! ensures that the command fails.
! OUTPUT=$(conda build --no-anaconda-upload symlinks/ 2>&1)
echo "$OUTPUT" | grep "Error" | wc -l | grep 6

! OUTPUT=$(conda build --no-anaconda-upload conda-meta/ 2>&1)
echo "$OUTPUT" | grep 'Error: Untracked file(s) ('\''conda-meta/nope'\'',)'

# Get the version of conda as the error message changed in conda 4.
set +e
echo $(conda -V 2>&1) | grep "conda 3\..*"
export IS_CONDA_3=$?
set -e

! OUTPUT=$(conda build --no-anaconda-upload recursive-build/ 2>&1)
if [[ $IS_CONDA_3 -eq 0 ]]; then
    echo "$OUTPUT" | grep 'No packages found in current .* channels matching: recursive-build2 2\.0'
else
    echo "$OUTPUT" |  tail -n2 | head -n1 | grep 'Package missing in current .* channels: '
    echo "$OUTPUT" |  tail -n1 | grep '  - recursive-build2 2.0'
fi

! OUTPUT=$(conda build --no-anaconda-upload source_git_jinja2_oops/ 2>&1)
echo "$OUTPUT" | grep '\''GIT_DSECRIBE_TAG'\'' is undefined'

echo "TESTS PASSED"
