#!/bin/bash

$PYTHON setup.py install

cp bdist_conda.py ${PREFIX}/lib/python${PY_VER}/distutils/command
