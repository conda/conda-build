.. _index:

Conda-build Documentation
=========================

Building a conda package requires
:doc:`installing conda-build <source/install-conda-build>` and
creating a conda :doc:`recipe <source/recipe>`. Use the ``conda build``
command to build the conda package from the conda recipe.

You can build conda packages from a variety of source code
projects, most notably Python. For help packing a Python project,
see the `Setuptools
documentation <https://setuptools.readthedocs.io/en/latest/>`_.

OPTIONAL: If you are planning to upload your packages to
Anaconda Cloud, you will need an
`Anaconda Cloud <http://anaconda.org>`_ account and client.

.. toctree::
   :maxdepth: 1

   source/install-conda-build
   source/concepts/index
   source/user-guide/index
   source/resources/index
   source/package-naming-conv
   source/features
   source/environment-variables
   source/debugging
   source/sample-recipes
   source/build-without-recipe
   source/wheel-files
   source/commands/index
   source/release-notes
   source/wheel-files

