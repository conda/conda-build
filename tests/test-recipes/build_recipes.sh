#!/bin/bash

set -e
set -x

cd "$(dirname "${BASH_SOURCE[0]}")"

# Recipes that should fail and give some error

for recipe in metadata/*/; do
    if [[ $(ls -A "$recipe") ]]; then
        if [[ $recipe =~ .*osx_is_app.* && $(uname) != "Darwin" ]]; then
            continue
        fi
        conda build --no-anaconda-upload $recipe
    fi
done

cd fail

# We use 2>&1 as the error is printed to stderr. We could do >/dev/null to
# ensure it is printed to stderr, but then we would hide the output of the
# command from the test output.  The ! ensures that the command fails.
! OUTPUT=$(conda build --no-anaconda-upload symlinks/ 2>&1)
echo "$OUTPUT" | grep "Error" | wc -l | grep 6

! OUTPUT=$(conda build --no-anaconda-upload conda-meta/ 2>&1)
echo "$OUTPUT" | grep 'Error: Untracked file(s) ('\''conda-meta/nope'\'',)'

! OUTPUT=$(conda build --no-anaconda-upload recursive-build/ 2>&1)
echo "$OUTPUT" | grep 'No packages found in current .* channels matching: recursive-build2 2\.0'

echo "TESTS PASSED"
