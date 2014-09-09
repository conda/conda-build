#!/bin/bash

set -e
set -x

for recipe in */*; do
    conda build $recipe
done
