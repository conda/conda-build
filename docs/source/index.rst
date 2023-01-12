.. _index:

Conda-build documentation
=========================

Conda-build contains commands and tools to use conda to build your
own packages.
It also provides helpful tools to constrain or pin
versions in recipes. Building a conda package requires
:doc:`installing conda-build <install-conda-build>` and
creating a conda :doc:`recipe <concepts/recipe>`.
You then use the ``conda build`` command to build the conda package
from the conda recipe.

You can build conda packages from a variety of source code
projects, most notably Python. For help packing a Python project,
see the `packaging.python.org tutorial`_.

OPTIONAL: If you are planning to upload your packages to
Anaconda Cloud, you will need an
`Anaconda Cloud <http://anaconda.org>`_ account and client.

.. toctree::
   :maxdepth: 1

   install-conda-build
   concepts/index
   user-guide/index
   resources/index
   release-notes
   contributing-guide


.. _`packaging.python.org tutorial`: https://packaging.python.org/en/latest/tutorials/packaging-projects
