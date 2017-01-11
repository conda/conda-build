#!/bin/bash

pip install --no-deps .

cp bdist_conda.py ${PREFIX}/lib/python${PY_VER}/distutils/command
