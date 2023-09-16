===================================
Installing and updating conda-build
===================================

To enable building conda packages:

* `install conda <https://conda.io/projects/conda/en/latest/user-guide/install/index.html>`_
* install conda-build
* update conda and conda-build


.. _-conda-build-wow:

Way of working
==============

For proper functioning, it is strongly recommended to install conda-build in
the conda ``base`` environment. Not doing so may lead to problems.

Explanation
-----------

With earlier conda / conda-build versions, it was possible to build packages in
your own defined environment, e.g. ``my_build_env``. This was partly driven by
the general conda recommendation not to use the ``base`` env for normal work;
see `Conda Managing Environments`_ for instance. However, conda-build is better
viewed as part of the conda infrastructure, and not as a normal package. Hence,
installing it in the ``base`` env makes more sense. More information:
`Must conda-build be installed in the base envt?`_

Other considerations
--------------------

* An installation or update of conda-build (in fact, of any package) in the ``base``
  environment needs to be run from an account with the proper permissions
  (i.e., the same permissions as were used to install conda and the base env in
  the first place via the Miniconda or Anaconda installers). For example, on
  Windows that might mean an account with administrator privileges.

* `conda-verfiy`_ is a useful package that can also be added to the base
  environment in order to remove some warnings generated when conda-build runs.

* For critical CI/CD projects, you might want to pin to an explicit (but recent)
  version of conda-build, i.e. only update to a newer version of conda-build
  and conda once they have been first verified "offline".


.. _install-conda-build:

Installing conda-build
======================

To install conda-build, in your terminal window or an Anaconda Prompt, run:

.. code-block:: bash

   conda activate base
   conda install conda-build


Updating conda and conda-build
==============================

Keep your versions of conda and conda-build up to date to
take advantage of bug fixes and new features.

To update conda and conda-build, in your terminal window or an Anaconda Prompt, run:

.. code-block:: bash

  conda activate base
  conda update conda
  conda update conda-build

For release notes, see the `conda-build GitHub
page <https://github.com/conda/conda-build/releases>`_.


.. _`Conda Managing Environments`:                      https://conda.io/projects/conda/en/latest/user-guide/getting-started.html#managing-environments
.. _`conda-verfiy`:                                     https://github.com/conda/conda-verify
.. _`Must conda-build be installed in the base envt?`:  https://github.com/conda/conda-build/issues/4995
