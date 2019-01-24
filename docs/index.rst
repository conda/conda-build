.. _index:

=========================
Conda-build Documentation
=========================

Building a conda package requires
:doc:`installing conda build <install-conda-build>` and
creating a conda :doc:`recipe <recipe>`. Use the ``conda build``
command to build the conda package from the conda recipe.

You can build conda packages from a variety of source code
projects, most notably Python. For help packing a Python project,
see the `Setuptools
documentation <https://setuptools.readthedocs.io/en/latest/>`_.

OPTIONAL: If you are planning to upload your packages to
Anaconda Cloud, you will need an
`Anaconda Cloud <http://anaconda.org>`_ account and client.

.. toctree::
   :maxdepth: 3

   source/install-conda-build
   source/conda-package-walkthrough/index
   source/package-spec
   source/package-naming-conv
   source/recipe
   source/channels
   source/define-metadata
   source/build-scripts
   source/features
   source/environment-variables
   source/make-relocatable
   source/link-scripts
   source/variants
   source/use-shared-libraries
   source/compiler-tools
   source/add-win-start-menu-items
   source/sample-recipes
   source/build-without-recipe
   source/wheel-files
   source/commands/index
