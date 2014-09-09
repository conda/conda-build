#!/bin/bash

set -e
set -x

for recipe in */*; do
    conda build --no-binstar-upload $recipe
done
