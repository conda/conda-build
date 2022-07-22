===========
conda-build
===========

.. image:: https://github.com/conda/conda-build/actions/workflows/tests.yml/badge.svg
  :target: https://github.com/conda/conda-build/actions/workflows/tests.yml

.. image:: https://codecov.io/gh/conda/conda-build/branch/master/graph/badge.svg
  :target: https://codecov.io/gh/conda/conda-build


Installation
--------------
.. code:: bash

    # Display information about current conda install
    conda info

    # Install conda-build in the current 'root' env
    conda install -n root conda-build


Building Your Own Packages
--------------------------

You can easily build your own packages for ``conda``, and upload them to `anaconda.org
<https://anaconda.org>`_, a free service for hosting packages for ``conda``, as
well as other package managers. To build a package, create a recipe. See
http://github.com/conda/conda-recipes for many example recipes, and
http://conda.pydata.org/docs/build.html for documentation on how to build
recipes.

To upload to anaconda.org, create an account.  Then, install the ``anaconda-client``
and login

.. code-block:: bash

   $ conda install anaconda-client
   $ anaconda login

Then, after you build your recipe

.. code-block:: bash

   $ conda build <recipe-dir>

you will be prompted to upload to anaconda.org.

To add your anaconda.org channel, or the channel of others to ``conda`` so that ``conda
install`` will find and install their packages, run

.. code-block:: bash

   $ conda config --add channels https://conda.anaconda.org/username

(replacing ``username`` with the user name of the person whose channel you want
to add).

Gotchas/FAQ
-----------

* ```OSError: [Errno 36] File name too long:``` - This error has been seen on Linux computers with encrypted folders.  The solution is to install ``miniconda`` or ``anaconda`` to a location that is not encrypted.  This error occurs because the encrypted form of the path that ``conda-build`` creates can be too long.

Getting Help
------------

The documentation for ``conda`` is at http://conda.pydata.org/docs/. You can
subscribe to the `conda mailing list
<https://groups.google.com/a/continuum.io/forum/#!forum/conda>`_.  The source
code and issue tracker for ``conda`` are on `GitHub <https://github.com/pydata/conda>`_.

Contributing to conda-build
---------------------------

Below is a short guide to setting up a local development environment for ``conda-build``.
This will allow you to develop new features and contribute your own bug fixes.

Requirements:

- Installation of `conda <https://github.com/conda/conda>`_ (see `Miniconda Installers <https://docs.conda.io/en/latest/miniconda.html>`_ for more information)
- A fork of ``conda-build`` (see `GitHub's guide on forking a repo <https://docs.github.com/en/get-started/quickstart/fork-a-repo>`_ for more information)

Setting up your environment
===========================

The first step to developing ``conda-build`` is create a new ``conda`` environment with
the latest version of ``conda`` installed. You can do that with the following command:

.. code-block:: bash

   $ conda create -n conda-build-dev -y conda
   $ conda activate conda-build-dev

Once that is complete, ``cd`` to your forked, cloned repository and run the following
command:

.. code-block:: bash

   $ pip install -e .

This will install all of the project dependencies, including a local version of ``conda-build``
that you will be able to run.

To install test dependencies, run the following ``conda`` command:

.. code-block:: bash

   $ conda install --file tests/requirements.txt -c defaults -y

After that has completed, you can run ``conda-build`` commands like so:

.. code-block:: bash

   $ conda-build --help

It is important to remember the hyphen between "conda" and "build". Otherwise, it is
very likely that your default installation will be found first on your path and used
instead. All other ``conda-build`` sub-commands (``render``, ``debug``, etc.) should
be invoke in a similar manner.

Running tests
=============

To run tests, use ``pytest`` like in the following example:

.. code-block:: bash

   $ pytest tests

Running individual tests can be accomplished with the following example:

.. code-block:: bash

   $ pytest tests/test_api_debug.py::test_debug_recipe_default_path

The configuration options for ``pytest`` are located in the ``setup.cfg`` file in
the root of the repository.

For more information on ``pytest`` `please see their documentation <https://docs.pytest.org/en/stable/>`_
