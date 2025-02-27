# conda-build/tests/test-recipes/test-package
# cd $RECIPE_DIR/../../test-package

# pip install .
python setup.py install --old-and-unmanageable
