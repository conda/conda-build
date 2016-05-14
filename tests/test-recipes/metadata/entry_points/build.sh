DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# conda-build/tests/test-recipes/test-package
cd $DIR/../../test-package

python setup.py install
