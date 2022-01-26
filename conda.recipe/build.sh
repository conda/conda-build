#!/bin/bash

python setup.py install --single-version-externally-managed --record=record.txt

cp bdist_conda.py ${PREFIX}/lib/python${PY_VER}/distutils/command

# required for distutils included in setuptools >=60.0.0
# see also https://setuptools.pypa.io/en/latest/history.html#v60-0-0
SETUPTOOLS_DISTUTILS="${PREFIX}/lib/python${PY_VER}/site-packages/setuptools/_distutils/command/"
mkdir -p "${SETUPTOOLS_DISTUTILS}"
cp bdist_conda.py "${SETUPTOOLS_DISTUTILS}"
