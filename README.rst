===========
conda-build
===========


Building Your Own Packages
--------------------------

You can easily build your own packages for conda, and upload them to `Binstar
<https://binstar.org>`_, a free service for hosting packages for conda, as
well as other package managers.  To build a package, create a recipe.  See
http://github.com/pydata/conda-recipes for many example recipes, and
http://docs.continuum.io/conda/build.html for documentation on how to build
recipes.

To upload to Binstar, create an account on binstar.org.  Then, install the
binstar client and login

.. code-block:: bash

   $ conda install binstar
   $ binstar login

Then, after you build your recipe

.. code-block:: bash

   $ conda build <recipe-dir>

you will be prompted to upload to binstar.

To add your Binstar channel, or the channel of others to conda so that ``conda
install`` will find and install their packages, run

.. code-block:: bash

   $ conda config --add channels https://conda.binstar.org/username

(replacing ``username`` with the user name of the person whose channel you want
to add).

Getting Help
------------

The documentation for conda is at http://docs.continuum.io/conda/. You can
subscribe to the `conda mailing list
<https://groups.google.com/a/continuum.io/forum/#!forum/conda>`_.  The source
code and issue tracker for conda are on `GitHub <https://github.com/pydata/conda>`_.

--------

Contents:

.. toctree::
   :maxdepth: 2

   miniconda.rst
