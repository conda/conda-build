#!/bin/bash

set -e
set -x

cd $(dirname ${BASH_SOURCE[0]})

for recipe in metadata/*/; do
    if [[ $(ls -A $recipe) ]]; then
        if [[ $recipe =~ .*osx_is_app.* && $(uname) != "Darwin" ]]; then
            continue
        fi
        conda build --no-binstar-upload $recipe
    fi
done
