#!/bin/bash
set -x
set -e
DIR=`mktemp -d -t sympy-0.7.5`
conda skeleton pypi --output-dir $DIR --version=0.7.5 sympy
python -c "
import yaml
with open('"$(dirname "${BASH_SOURCE[0]}")"/sympy-0.7.5/meta.yaml') as f:
    expected = yaml.load(f)
with open('$DIR/sympy/meta.yaml') as f:
    actual = yaml.load(f)
assert expected == actual
"
# XXX: This won't run if the test fails.
rm -rf $DIR
echo passed
