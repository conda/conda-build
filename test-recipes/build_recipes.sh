#!/bin/bash

set -e
set -x

cd $(dirname ${BASH_SOURCE[0]})

for recipe in metadata/*/; do
    conda build --no-binstar-upload $recipe
done
