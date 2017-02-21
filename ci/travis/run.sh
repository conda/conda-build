# flake8 and bdist_conda test together
set -ev
if [[ "$FLAKE8" == "true" ]]; then
    flake8 .
    cp bdist_conda.py $HOME/miniconda/lib/python${TRAVIS_PYTHON_VERSION}/distutils/command
    pushd tests/bdist-recipe && python setup.py bdist_conda && popd
    conda build --help
    conda build conda.recipe --no-anaconda-upload -c conda-forge
    conda create -n _cbtest python=$TRAVIS_PYTHON_VERSION
    source activate _cbtest
    conda install $(conda render --output conda.recipe)
    conda install filelock
    conda build conda.recipe --no-anaconda-upload -c conda-forge
else
    $HOME/miniconda/bin/py.test -v -n 0 --basetemp /tmp/cb --cov conda_build --cov-report xml -m "serial" tests
    $HOME/miniconda/bin/py.test -v -n 2 --basetemp /tmp/cb --cov conda_build --cov-append --cov-report xml -m "not serial" tests --durations=15
fi
