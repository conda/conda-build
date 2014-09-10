#!/bin/bash

set -e
set -x

cd $(dirname ${BASH_SOURCE[0]})

for recipe in */*/; do
    conda build --no-binstar-upload $recipe
done
