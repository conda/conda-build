# flake8 and bdist_conda test together
set -ev
if [[ "$FLAKE8" == "true" ]]; then
    flake8 .
    dirname="$(find /opt/conda/lib -iname python* -type d -maxdepth 1)"
    cp bdist_conda.py $dirname/distutils/command
    pushd tests/bdist-recipe && python setup.py bdist_conda && popd
    conda build --help
    conda build --version
    conda render conda.recipe
    conda build conda.recipe --no-anaconda-upload
    conda create -n _cbtest conda-build glob2 six
    # because this is a file, conda is not going to process any of its dependencies.
    conda install -n _cbtest $(conda render --output conda.recipe | head -n 1)
    source activate _cbtest
    conda build conda.recipe --no-anaconda-upload
elif [[ "$DOCS" == "true" ]]; then
    cd docs
    make html
else
    FILES_CHANGED=$(git diff master --name-only | wc -l)
    DOCS_FILES_CHANGED=$(git diff master --name-only | grep docs | wc -l)
    if [[ $FILES_CHANGED == $DOCS_FILES_CHANGED ]]; then
      echo "Only docs changed detected, skipping tests"
    else
      echo "safety_checks: disabled" >> ~/.condarc
      echo "local_repodata_ttl: 1800" >> ~/.condarc
      mkdir -p ~/.conda
      conda create -n blarg1 -yq python=2.7
      conda create -n blarg3 -yq python=3.5
      conda create -n blarg4 -yq python nomkl numpy pandas svn
      /opt/conda/bin/py.test -v -n 2 --basetemp /tmp/cb --cov conda_build --cov-append --cov-report xml -m "not serial" tests --forked
      # install conda-verify from its master branch, at least for a while until it's more stable
      pip install git+https://github.com/conda/conda-verify.git
      /opt/conda/bin/py.test -v -n 0 --basetemp /tmp/cb --cov conda_build --cov-report xml -m "serial" tests
    fi
fi
