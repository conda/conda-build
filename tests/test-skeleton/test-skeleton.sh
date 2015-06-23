#!/bin/bash
set -x
set -e
DIR=`mktemp -d -t sympy-0.7.5-XXXX`
conda skeleton pypi --output-dir $DIR --version=0.7.5 sympy
python -c "
import yaml
with open('"$(dirname "${BASH_SOURCE[0]}")"/sympy-0.7.5/meta.yaml') as f:
    expected = yaml.load(f)
with open('$DIR/sympy/meta.yaml') as f:
    actual = yaml.load(f)
assert expected == actual, (expected, actual)
"
# XXX: This won't run if the test fails.
rm -rf $DIR
echo passed

DIR=`mktemp -d -t sympy-0.7.5-url-XXXX`
conda skeleton pypi --output-dir $DIR https://pypi.python.org/packages/source/s/sympy/sympy-0.7.5.tar.gz#md5=7de1adb49972a15a3dd975e879a2bea9
python -c "
import yaml
with open('"$(dirname "${BASH_SOURCE[0]}")"/sympy-0.7.5-url/meta.yaml') as f:
    expected = yaml.load(f)
with open('$DIR/sympy/meta.yaml') as f:
    actual = yaml.load(f)
assert expected == actual, (expected, actual)
"
# XXX: This won't run if the test fails.
rm -rf $DIR
echo passed
