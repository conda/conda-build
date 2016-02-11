#!/bin/bash

cp $RECIPE_DIR/foo.py $SRC_DIR
cp $RECIPE_DIR/setup.py $SRC_DIR

$PYTHON setup.py install
