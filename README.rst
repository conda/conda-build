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

We always welcome new contributors for ``conda-build``, especially for bug fixes and
new feature requests. To help get your environment set up and begin developing, please
refer to our `Contributing Guide <CONTRIBUTING.md>`_.
