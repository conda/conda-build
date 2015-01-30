#!/bin/bash

$PYTHON setup.py install

EXAMPLES=$PREFIX/Examples
mkdir $EXAMPLES
mv examples $EXAMPLES/bokeh
