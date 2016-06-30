===========
conda-build
===========

.. image:: https://travis-ci.org/conda/conda-build.svg?branch=master
               :target: https://travis-ci.org/conda/conda-build

.. image:: https://ci.appveyor.com/api/projects/status/wdis0rkcfdoeql3x?svg=true
               :target: https://ci.appveyor.com/project/ContinuumAnalytics/conda-build
               
.. image:: https://anaconda.org/conda-team/conda-build/badges/build.svg
               :target: https://anaconda.org/conda-team/conda-build/
               
.. image:: https://www.quantifiedcode.com/api/v1/project/1960a96404aa431bab5d834edff1cf85/badge.svg
  :target: https://www.quantifiedcode.com/app/project/1960a96404aa431bab5d834edff1cf85
  :alt: Code issues
  
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

Getting Help
------------

The documentation for conda is at http://conda.pydata.org/docs/. You can
subscribe to the `conda mailing list
<https://groups.google.com/a/continuum.io/forum/#!forum/conda>`_.  The source
code and issue tracker for conda are on `GitHub <https://github.com/pydata/conda>`_.


Contributing
------------

Contributions to conda-build are always welcome!  Please fork the conda/conda-build repository, and submit a PR.  If a PR is a work in progress, please put [WIP] in the title.  Contributions are expected to pass flake8 and test suites run on Travis CI (linux) and AppVeyor (windows).  Contributors also need to have signed our `Contributor License Agreement <https://www.clahub.com/agreements/conda/conda-build>`_

teststuff
