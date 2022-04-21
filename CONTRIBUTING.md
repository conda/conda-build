# Contributing to `conda-build`

## New Issues

If your issue is a bug report or a feature request for:

* **a specific conda package**: please file it at <https://github.com/ContinuumIO/anaconda-issues/issues>
* **anaconda.org**: please file it at <https://anaconda.org/contact/report>
* **repo.anaconda.com**: please file it at <https://github.com/ContinuumIO/anaconda-issues/issues>
* **commands under `conda env` and all other conda commands**: please file it at <https://github.com/conda/conda/issues>

## Code of Conduct

The `conda` organization adheres to the [NumFOCUS Code of Conduct](https://www.numfocus.org/code-of-conduct).

## Contributing

Contributions to `conda-build` are always welcome! Please fork the
`conda/conda-build` repository, and submit a pull request (PR).

If a PR is a work in progress, please put [WIP] in the title. Contributions are
expected to pass `flake8` and test suites run on the GitHub Actions Pipeline. Contributors also
need to have signed our [Contributor License Agreement](https://conda.io/en/latest/contributing.html#conda-contributor-license-agreement).

## Setting Up Your Environment

There are two ways to set up your environment for development/testing. The first
is to reuse your base environment; this is probably the easiest option but comes
with the risk of potentially breaking `conda/conda-build`. The second option is to
create a development environment where we install `conda/conda-build`, which won't
impact the functionality of `conda/conda-build` installed in your base environment.

#### Using the Base Environment:

``` bash
    # activate/install into base env
    $ conda activate base
    (base) $ conda install --file tests/requirements.txt --channel defaults

    # run tests
    (base) $ pytest

    # install as editable so you can play around with it
    (base) $ pip install -e .
    (base) $ conda-build --version
    conda-build 3.21.5+17.gcde7b306
```

#### Creating a Development Environment:

``` bash
    # create/activate standalone dev env
    $ CONDA_ENV=conda-build make setup
    $ conda activate conda-build

    # Run all tests on Linux and Mac OS X systems (this can take a long time)
    (conda-build) $ make test

    # install as editable so you can play around with it
    (dev) $ pip install -e .
    (dev) $ conda-build --version
    conda-build 3.21.5+17.gcde7b306
```

## Testing

Running our test suite requires cloning one other repo at the same level as `conda-build`:
https://github.com/conda/conda_build_test_recipe - this is necessary for relative path tests
outside of `conda-build`'s build tree.

Follow the installation instructions above to properly set up your environment for testing.

The test suite runs with `py.test`. The following are some useful commands for running specific
tests, assuming you are in the `conda-build` root folder:

### Run all tests:
```bash
    # On Linux and Mac OS X
    make test
```

### Run one test file:
```bash
    py.test tests/test_api_build.py
```

### Run one test function:
```bash
    py.test tests/test_api_build.py::test_early_abort
```

### Run one parameter of one parametrized test function:

Several tests are parametrized, to run some small change, or build several
recipe folders. To choose only one of them::
```bash
    py.test tests/test_api_build.py::test_recipe_builds.py[entry_points]
```
Note that our tests use `py.test` fixtures extensively. These sometimes trip up IDE
style checkers about unused or redefined variables. These warnings are safe to
ignore.

## Releasing

Releases of `conda-build`may be performed via the [`rever` command](https://regro.github.io/rever-docs/).
Rever is configured to perform the activities for a typical conda-build release.
To cut a release, simply run `rever <X.Y.Z>` where `<X.Y.Z>` is the
release number that you want bump to. For example, `rever 1.2.3`. However,
it is always good idea to make sure that the you have permissions everywhere
to actually perform the release. So it is customary to run `rever check` before
the release, just to make sure. The standard workflow is thus:

```
    rever check
    rever 1.2.3
```

If for some reason a release fails partway through, or you want to claw back a
release that you have made, `rever` allows you to undo activities. If you find yourself
in this pickle, you can pass the `--undo` option a comma-separated list of
activities you'd like to undo. For example:
```
    rever --undo tag,changelog,authors 1.2.3
```

Happy releasing!
