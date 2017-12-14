install_conda_43() {
    rm -rf $HOME/miniconda/lib/python$TRAVIS_PYTHON_VERSION/site-packages/conda;
    rm -rf $HOME/miniconda/lib/python$TRAVIS_PYTHON_VERSION/site-packages/conda*.egg-info;
    git clone -b $CONDA_VERSION --single-branch --depth 1000 https://github.com/conda/conda.git;
    pushd conda;
    $HOME/miniconda/bin/python utils/setup-testing.py install;
    popd;
    hash -r;
    conda info;
}


install_conda_44() {
    rm -rf $HOME/miniconda/lib/python$TRAVIS_PYTHON_VERSION/site-packages/conda
    rm -rf $HOME/miniconda/lib/python$TRAVIS_PYTHON_VERSION/site-packages/conda*.egg-info
    rm -rf $HOME/miniconda/bin/activate
    rm -rf $HOME/miniconda/bin/conda
    rm -rf $HOME/miniconda/bin/conda-env
    rm -rf $HOME/miniconda/bin/deactivate

    git clone -b $CONDA_VERSION --single-branch --depth 1000 https://github.com/conda/conda.git $HOME/conda

    pushd $HOME/conda
    $HOME/miniconda/bin/python conda.recipe/setup.py install
    popd

    . $HOME/conda/utils/functions.sh
    install_conda_shell_scripts $HOME/miniconda "$HOME/conda"
    make_conda_entrypoint $HOME/miniconda/bin/conda $HOME/miniconda/bin/python "$HOME/conda" 'from conda.cli import main'
    make_conda_entrypoint $HOME/miniconda/bin/conda-env $HOME/miniconda/bin/python "$HOME/conda" 'from conda_env.cli.main import main'

    . "$HOME/miniconda/etc/profile.d/conda.sh"

    conda info

    echo "safety_checks: disabled" >> "$HOME/.condarc"

}


case "$CONDA_VERSION" in
  4.3*) install_conda_43;;
  *) install_conda_44;;
esac
