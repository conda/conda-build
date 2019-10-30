===========
conda-build
===========

.. image:: https://dev.azure.com/anaconda-conda/conda-build/_apis/build/status/conda.conda-build?branchName=master
  :target: https://dev.azure.com/anaconda-conda/conda-build/_build/latest?definitionId=1&branchName=master

.. image:: https://codecov.io/gh/conda/conda-build/branch/master/graph/badge.svg
  :target: https://codecov.io/gh/conda/conda-build


Installation
--------------
.. code:: bash

    # Display information about current conda install
    conda info

    # Install conda-build in the current env
    conda install -n root conda-build


Building Your Own Packages
--------------------------

You can easily build your own packages for conda, and upload them to `anaconda.org
<https://anaconda.org>`_, a free service for hosting packages for conda, as
well as other package managers.  To build a package, create a recipe.  See
http://github.com/conda/conda-recipes for many example recipes, and
http://conda.pydata.org/docs/build.html for documentation on how to build
recipes.

To upload to anaconda.org, create an account.  Then, install the anaconda-client
and login

.. code-block:: bash

   $ conda install anaconda-client
   $ anaconda login

Then, after you build your recipe

.. code-block:: bash

   $ conda build <recipe-dir>

you will be prompted to upload to anaconda.org.

To add your anaconda.org channel, or the channel of others to conda so that ``conda
install`` will find and install their packages, run

.. code-block:: bash

   $ conda config --add channels https://conda.anaconda.org/username

(replacing ``username`` with the user name of the person whose channel you want
to add).

Gotchas/FAQ
-----------

* ```OSError: [Errno 36] File name too long:``` - This error has been seen on Linux computers with encrypted folders.  The solution is to install miniconda or anaconda to a location that is not encrypted.  This error occurs because the encrypted form of the path that conda-build creates can be too long.

Getting Help
------------

The documentation for conda is at http://conda.pydata.org/docs/. You can
subscribe to the `conda mailing list
<https://groups.google.com/a/continuum.io/forum/#!forum/conda>`_.  The source
code and issue tracker for conda are on `GitHub <https://github.com/pydata/conda>`_.


Contributing
------------

Contributions to conda-build are always welcome! Please fork the
conda/conda-build repository, and submit a PR. If a PR is a work in progress,
please put [WIP] in the title. Contributions are expected to pass flake8 and
test suites run on Travis CI (linux) and AppVeyor (windows). Contributors also
need to have signed our `Contributor License Agreement
<https://www.clahub.com/agreements/conda/conda-build>`_

Testing
-------

Running our test suite requires cloning one other repo at the same level as conda-build:
https://github.com/conda/conda_build_test_recipe - this is necessary for relative path tests
outside of conda build's build tree.

Additionally, you need to install a few extra packages:

.. code-block:: bash

  conda install anaconda-client pytest pytest-cov mock pytest-mock conda-package-handling python-libarchive-c

The test suite runs with py.test. Some useful commands to run select tests,
assuming you are in the conda-build root folder:

Run all tests:
==============

    py.test tests

Run one test file:
======================

    py.test tests/test_api_build.py

Run one test function:
======================

    py.test tests/test_api_build.py::test_early_abort

Run one parameter of one parametrized test function:
====================================================

Several tests are parametrized, to run some small change, or build several
recipe folders. To choose only one of them::

    py.test tests/test_api_build.py::test_recipe_builds.py[entry_points]

Note that our tests use py.test fixtures extensively. These sometimes trip up IDE
style checkers about unused or redefined variables. These warnings are safe to
ignore.

Releasing
---------

Conda-build releases may be performed via the `rever command <https://regro.github.io/rever-docs/>`_.
Rever is configured to perform the activities for a typical conda-build release.
To cut a release, simply run ``rever <X.Y.Z>`` where ``<X.Y.Z>`` is the
release number that you want bump to. For example, ``rever 1.2.3``.  However,
it is always good idea to make sure that the you have permissions everywhere
to actually perform the release.  So it is customary to run ``rever check`` before
the release, just to make sure.  The standard workflow is thus::

    rever check
    rever 1.2.3

If for some reason a release fails partway through, or you want to claw back a
release that you have made, rever allows you to undo activities. If you find yourself
in this pickle, you can pass the ``--undo`` option a comma-separated list of
activities you'd like to undo.  For example::

    rever --undo tag,changelog,authors 1.2.3

Happy releasing!
